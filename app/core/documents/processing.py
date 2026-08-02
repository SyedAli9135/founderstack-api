"""
Document ingestion pipeline
Extracts text from an uploaded file (PDF/DOCX/TXT/MD), splits it into
overlapping chunks, embeds them via Cohere, and upserts the vectors into the
org's Pinecone RAG namespace. Mirrors app/core/mcp/registry/seed.py
sync SDK calls (Cohere, Pinecone) are offloaded to a thread via
`run_in_executor` so they never block the event loop — the same pattern
app/api/v1/health.py uses for its Pinecone liveness check.
"""

import asyncio
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import cohere
from docx import Document as DocxReader
from pinecone import Pinecone
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete, select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.core.storage import s3
from app.models.knowledge import Document, DocumentChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Upload validation config
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

# ---------------------------------------------------------------------------
# Chunking / embedding config
# ---------------------------------------------------------------------------

CHUNK_SIZE = 1024
CHUNK_OVERLAP = 128

# dim=1024, matches the founderstack-rag Pinecone index
EMBED_MODEL = "embed-multilingual-v3.0"
EMBED_INPUT_TYPE = "search_document"
EMBED_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def get_extension(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""


def extract_text(filename: str, data: bytes) -> str:
    """Extract raw text from an uploaded file based on its extension."""
    ext = get_extension(filename)
    if ext == ".pdf":
        return _extract_pdf(data)
    if ext == ".docx":
        return _extract_docx(data)
    if ext in (".txt", ".md"):
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported file extension: {ext}")


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _extract_docx(data: bytes) -> str:
    doc = DocxReader(io.BytesIO(data))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks via RecursiveCharacterTextSplitter."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return [c for c in splitter.split_text(text) if c.strip()]


# ---------------------------------------------------------------------------
# Embedding (Cohere)
# ---------------------------------------------------------------------------

async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed chunk texts via Cohere, EMBED_BATCH_SIZE at a time."""
    def _embed_batch(batch: list[str]) -> list[list[float]]:
        co = cohere.Client(settings.COHERE_API_KEY.get_secret_value())
        response = co.embed(texts=batch, model=EMBED_MODEL,
                            input_type=EMBED_INPUT_TYPE)
        return list(response.embeddings)

    loop = asyncio.get_event_loop()
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        embeddings = await loop.run_in_executor(None, _embed_batch, batch)
        all_embeddings.extend(embeddings)
    return all_embeddings


# ---------------------------------------------------------------------------
# Pinecone (RAG index)
# ---------------------------------------------------------------------------

def pinecone_namespace(org_id: str) -> str:
    return f"org_{org_id}"


def build_vector_id(doc_id: str, chunk_index: int) -> str:
    return f"{doc_id}__{chunk_index}"


def build_chunk_metadata(
    org_id: str, doc_id: str, filename: str, category: str,
    chunk_index: int, total_chunks: int, text: str,
) -> dict:
    return {
        "org_id": org_id,
        "doc_id": doc_id,
        "filename": filename,
        "category": category,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
        # keep individual metadata entries well under Pinecone's per-vector limit
        "text": text[:2000],
    }


async def upsert_chunks(
    org_id: str,
    doc_id: str,
    filename: str,
    category: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> list[str]:
    """Upsert chunk embeddings into the org's Pinecone RAG namespace. Returns the vector ids used."""
    vector_ids = [build_vector_id(doc_id, i) for i in range(len(chunks))]
    vectors = [
        {
            "id": vector_ids[i],
            "values": embeddings[i],
            "metadata": build_chunk_metadata(org_id, doc_id, filename, category, i, len(chunks), chunks[i]),
        }
        for i in range(len(chunks))
    ]

    def _upsert():
        pc = Pinecone(api_key=settings.PINECONE_API_KEY.get_secret_value())
        index = pc.Index(settings.PINECONE_INDEX_RAG)
        namespace = pinecone_namespace(org_id)
        for i in range(0, len(vectors), 100):
            index.upsert(vectors=vectors[i:i + 100], namespace=namespace)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _upsert)
    return vector_ids


async def delete_vectors(org_id: str, vector_ids: list[str]) -> None:
    """Delete vectors from the org's Pinecone RAG namespace."""
    if not vector_ids:
        return

    def _delete():
        pc = Pinecone(api_key=settings.PINECONE_API_KEY.get_secret_value())
        index = pc.Index(settings.PINECONE_INDEX_RAG)
        index.delete(ids=vector_ids, namespace=pinecone_namespace(org_id))

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _delete)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def process_document(doc_id: str) -> None:
    """
    Full ingestion pipeline for a single document. Runs as a fire-and-forget
    background task after upload (and again on reindex): download from S3 ->
    extract text -> chunk -> embed -> upsert to Pinecone -> record
    document_chunks -> mark indexed. Any failure marks the document 'failed'
    with the error captured for the founder to see, rather than leaving it
    stuck in 'processing'.
    """
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, uuid.UUID(doc_id))
        if doc is None:
            logger.error(f"process_document: document {doc_id} not found")
            return

        try:
            doc.processing_status = "processing"
            await db.commit()

            data = await s3.download_bytes(doc.s3_path)
            text = extract_text(doc.filename, data)
            chunks = chunk_text(text)

            if not chunks:
                doc.processing_status = "indexed"
                doc.total_chunks = 0
                doc.indexed_at = datetime.now(timezone.utc)
                doc.error_detail = None
                await db.commit()
                return

            embeddings = await embed_texts(chunks)
            vector_ids = await upsert_chunks(
                org_id=str(doc.org_id),
                doc_id=str(doc.id),
                filename=doc.filename,
                category=doc.category or "general",
                chunks=chunks,
                embeddings=embeddings,
            )

            for i, vector_id in enumerate(vector_ids):
                db.add(DocumentChunk(doc_id=doc.id,
                       chunk_index=i, pinecone_id=vector_id))

            doc.processing_status = "indexed"
            doc.total_chunks = len(chunks)
            doc.indexed_at = datetime.now(timezone.utc)
            doc.error_detail = None
            await db.commit()
            logger.info(
                f"process_document: indexed {doc_id} ({len(chunks)} chunks)")
        except Exception as e:
            logger.exception(f"process_document: failed for {doc_id}: {e}")
            await db.rollback()
            doc = await db.get(Document, uuid.UUID(doc_id))
            if doc is not None:
                doc.processing_status = "failed"
                doc.error_detail = str(e)[:1000]
                await db.commit()


async def reindex_document(doc_id: str) -> None:
    """
    Re-embed a document with the latest embedding model/version: delete its
    existing Pinecone vectors + document_chunks rows, then run the standard
    ingestion pipeline again from the S3 source file.
    """
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, uuid.UUID(doc_id))
        if doc is None:
            logger.error(f"reindex_document: document {doc_id} not found")
            return

        result = await db.execute(select(DocumentChunk).where(DocumentChunk.doc_id == doc.id))
        old_vector_ids = [c.pinecone_id for c in result.scalars().all()]

        if old_vector_ids:
            await delete_vectors(str(doc.org_id), old_vector_ids)
        await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc.id))
        await db.commit()

    await process_document(doc_id)


async def purge_document_job(doc_id: str) -> None:
    """
    Permanently removes a soft-deleted document: Pinecone vectors, then the
    S3 object, then the document_chunks/documents rows — external systems
    are cleaned up before the DB rows so a failed/retried purge never
    orphans a vector or file with no DB record pointing at it.
    """
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, uuid.UUID(doc_id))
        if doc is None:
            logger.error(f"purge_document_job: document {doc_id} not found")
            return

        result = await db.execute(select(DocumentChunk).where(DocumentChunk.doc_id == doc.id))
        chunks = result.scalars().all()
        vector_ids = [c.pinecone_id for c in chunks]

        try:
            await delete_vectors(str(doc.org_id), vector_ids)
            await s3.delete_object(doc.s3_path)
        except Exception as e:
            logger.exception(
                f"purge_document_job: external cleanup failed for {doc_id}: {e}")
            return

        await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc.id))
        await db.execute(delete(Document).where(Document.id == doc.id))
        await db.commit()
        logger.info(f"purge_document_job: purged {doc_id}")
