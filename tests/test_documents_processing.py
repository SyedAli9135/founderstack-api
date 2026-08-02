"""
Unit tests for the Workflow 6 document ingestion pipeline
(app/core/documents/processing.py).

Pure helpers (text extraction, chunking, Pinecone id/metadata builders) are
exercised directly against real generated PDF/DOCX bytes — no mocking needed,
matching test_mcp_seed.py's approach for Workflow 5.

The orchestration functions (process_document/reindex_document/purge_document_job)
open their own DB session via `AsyncSessionLocal`, independent of the request-scoped
`get_db` override the other test files use. To exercise the real status-transition
logic against the isolated test database (rather than the dev DB from .env), the
`patch_processing_db` fixture below swaps `processing.AsyncSessionLocal` for one
bound to the test engine. External services (S3, Cohere, Pinecone) are monkeypatched
at the module boundary — hitting them for real is an integration-level concern.
"""

import io
import uuid

import pytest
from docx import Document as DocxWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.documents import processing
from app.models.knowledge import Document, DocumentChunk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_processing_db(monkeypatch, test_engine):
    """Point processing.py's background-task sessions at the test DB instead of the dev DB."""
    test_session_local = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(processing, "AsyncSessionLocal", test_session_local)


def _build_minimal_pdf(text: str) -> bytes:
    """Hand-build a minimal single-page PDF with a real, extractable text stream."""
    content = f"BT /F1 24 Tf 100 700 Td ({text}) Tj ET".encode()
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj",
        b"4 0 obj<</Length " + str(len(content)).encode() + b">>stream\n" + content + b"\nendstream endobj",
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj + b"\n"
    xref_start = len(pdf)
    pdf += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode()
    pdf += b"trailer<</Size " + str(len(objects) + 1).encode() + b"/Root 1 0 R>>\n"
    pdf += b"startxref\n" + str(xref_start).encode() + b"\n%%EOF"
    return pdf


def _build_docx(paragraph_text: str) -> bytes:
    doc = DocxWriter()
    doc.add_paragraph(paragraph_text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def test_get_extension_lowercases_and_handles_no_dot():
    assert processing.get_extension("Report.PDF") == ".pdf"
    assert processing.get_extension("notes.md") == ".md"
    assert processing.get_extension("noextension") == ""


def test_extract_text_txt():
    assert processing.extract_text("notes.txt", b"Hello plain text") == "Hello plain text"


def test_extract_text_md():
    assert processing.extract_text("readme.md", b"# Heading\n\nBody") == "# Heading\n\nBody"


def test_extract_text_pdf_returns_real_text():
    pdf_bytes = _build_minimal_pdf("Hello PDF World")
    assert "Hello PDF World" in processing.extract_text("agreement.pdf", pdf_bytes)


def test_extract_text_docx_returns_real_text():
    docx_bytes = _build_docx("Hello DOCX World")
    assert "Hello DOCX World" in processing.extract_text("sop.docx", docx_bytes)


def test_extract_text_unsupported_extension_raises():
    with pytest.raises(ValueError):
        processing.extract_text("archive.zip", b"whatever")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def test_chunk_text_splits_long_text_into_multiple_chunks():
    text = "Lorem ipsum dolor sit amet. " * 100  # ~2900 chars
    chunks = processing.chunk_text(text, chunk_size=200, chunk_overlap=40)

    assert len(chunks) > 1
    assert all(len(c) <= 200 + 40 for c in chunks)  # splitter may slightly exceed chunk_size to respect word boundaries


def test_chunk_text_short_text_returns_single_chunk():
    chunks = processing.chunk_text("Just one short sentence.", chunk_size=1024, chunk_overlap=128)
    assert chunks == ["Just one short sentence."]


def test_chunk_text_drops_empty_chunks():
    chunks = processing.chunk_text("   \n\n   ", chunk_size=100, chunk_overlap=10)
    assert chunks == []


# ---------------------------------------------------------------------------
# Pinecone id / metadata / namespace builders
# ---------------------------------------------------------------------------

def test_pinecone_namespace_prefixes_org_id():
    assert processing.pinecone_namespace("abc-123") == "org_abc-123"


def test_build_vector_id_joins_doc_and_chunk_index():
    assert processing.build_vector_id("doc-1", 3) == "doc-1__3"


def test_build_chunk_metadata_shape():
    metadata = processing.build_chunk_metadata(
        org_id="org-1", doc_id="doc-1", filename="terms.pdf", category="legal",
        chunk_index=0, total_chunks=5, text="Some chunk text",
    )
    assert metadata["org_id"] == "org-1"
    assert metadata["doc_id"] == "doc-1"
    assert metadata["filename"] == "terms.pdf"
    assert metadata["category"] == "legal"
    assert metadata["chunk_index"] == 0
    assert metadata["total_chunks"] == 5
    assert metadata["text"] == "Some chunk text"


def test_build_chunk_metadata_truncates_long_text():
    metadata = processing.build_chunk_metadata(
        org_id="org-1", doc_id="doc-1", filename="f.txt", category="general",
        chunk_index=0, total_chunks=1, text="x" * 5000,
    )
    assert len(metadata["text"]) == 2000


# ---------------------------------------------------------------------------
# Orchestration: process_document
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_document_success(patch_processing_db, db_session, setup_user_org, monkeypatch):
    org_id = setup_user_org["org_id"]
    doc = Document(
        org_id=org_id,
        filename="handbook.txt",
        s3_path=f"documents/{org_id}/some-doc/handbook.txt",
        mime_type="text/plain",
        byte_size=100,
        category="hr",
        processing_status="pending",
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    monkeypatch.setattr(processing.s3, "download_bytes", _async_return(b"Employee handbook content."))
    monkeypatch.setattr(processing, "embed_texts", _async_return([[0.1, 0.2, 0.3]]))
    monkeypatch.setattr(processing, "upsert_chunks", _async_return(["vec-0"]))

    await processing.process_document(str(doc.id))

    await db_session.refresh(doc)
    assert doc.processing_status == "indexed"
    assert doc.total_chunks == 1
    assert doc.indexed_at is not None
    assert doc.error_detail is None

    result = await db_session.execute(select(DocumentChunk).where(DocumentChunk.doc_id == doc.id))
    chunks = result.scalars().all()
    assert len(chunks) == 1
    assert chunks[0].pinecone_id == "vec-0"


@pytest.mark.asyncio
async def test_process_document_marks_failed_on_error(patch_processing_db, db_session, setup_user_org, monkeypatch):
    org_id = setup_user_org["org_id"]
    doc = Document(
        org_id=org_id,
        filename="broken.txt",
        s3_path=f"documents/{org_id}/broken-doc/broken.txt",
        mime_type="text/plain",
        byte_size=10,
        category="general",
        processing_status="pending",
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    async def _raise(*args, **kwargs):
        raise RuntimeError("S3 object not found")

    monkeypatch.setattr(processing.s3, "download_bytes", _raise)

    await processing.process_document(str(doc.id))

    await db_session.refresh(doc)
    assert doc.processing_status == "failed"
    assert "S3 object not found" in doc.error_detail


@pytest.mark.asyncio
async def test_process_document_empty_text_indexes_zero_chunks(patch_processing_db, db_session, setup_user_org, monkeypatch):
    org_id = setup_user_org["org_id"]
    doc = Document(
        org_id=org_id,
        filename="empty.txt",
        s3_path=f"documents/{org_id}/empty-doc/empty.txt",
        mime_type="text/plain",
        byte_size=0,
        category="general",
        processing_status="pending",
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    monkeypatch.setattr(processing.s3, "download_bytes", _async_return(b"   "))

    await processing.process_document(str(doc.id))

    await db_session.refresh(doc)
    assert doc.processing_status == "indexed"
    assert doc.total_chunks == 0


@pytest.mark.asyncio
async def test_process_document_missing_doc_is_a_noop(patch_processing_db):
    # Should not raise even though no document exists with this id.
    await processing.process_document(str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Orchestration: purge_document_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purge_document_job_deletes_vectors_file_and_rows(patch_processing_db, db_session, setup_user_org, monkeypatch):
    org_id = setup_user_org["org_id"]
    doc = Document(
        org_id=org_id,
        filename="old.txt",
        s3_path=f"documents/{org_id}/old-doc/old.txt",
        mime_type="text/plain",
        byte_size=10,
        category="general",
        processing_status="deleting",
        total_chunks=2,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    db_session.add(DocumentChunk(doc_id=doc.id, chunk_index=0, pinecone_id="vec-0"))
    db_session.add(DocumentChunk(doc_id=doc.id, chunk_index=1, pinecone_id="vec-1"))
    await db_session.commit()

    deleted_vector_calls = []
    deleted_s3_keys = []

    async def _fake_delete_vectors(org_id_arg, vector_ids):
        deleted_vector_calls.append((org_id_arg, vector_ids))

    async def _fake_delete_object(key):
        deleted_s3_keys.append(key)

    monkeypatch.setattr(processing, "delete_vectors", _fake_delete_vectors)
    monkeypatch.setattr(processing.s3, "delete_object", _fake_delete_object)

    await processing.purge_document_job(str(doc.id))

    assert deleted_vector_calls == [(str(org_id), ["vec-0", "vec-1"])]
    assert deleted_s3_keys == [doc.s3_path]

    doc_result = await db_session.execute(select(Document).where(Document.id == doc.id))
    assert doc_result.scalar_one_or_none() is None

    chunk_result = await db_session.execute(select(DocumentChunk).where(DocumentChunk.doc_id == doc.id))
    assert chunk_result.scalars().all() == []


@pytest.mark.asyncio
async def test_purge_document_job_keeps_rows_if_external_cleanup_fails(patch_processing_db, db_session, setup_user_org, monkeypatch):
    org_id = setup_user_org["org_id"]
    doc = Document(
        org_id=org_id,
        filename="stuck.txt",
        s3_path=f"documents/{org_id}/stuck-doc/stuck.txt",
        mime_type="text/plain",
        byte_size=10,
        category="general",
        processing_status="deleting",
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    async def _raise(*args, **kwargs):
        raise RuntimeError("Pinecone unavailable")

    monkeypatch.setattr(processing, "delete_vectors", _raise)

    await processing.purge_document_job(str(doc.id))

    # Row must survive so a later retry can find and purge it again.
    doc_result = await db_session.execute(select(Document).where(Document.id == doc.id))
    assert doc_result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Orchestration: reindex_document
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reindex_document_replaces_old_chunks(patch_processing_db, db_session, setup_user_org, monkeypatch):
    org_id = setup_user_org["org_id"]
    doc = Document(
        org_id=org_id,
        filename="policy.txt",
        s3_path=f"documents/{org_id}/policy-doc/policy.txt",
        mime_type="text/plain",
        byte_size=20,
        category="legal",
        processing_status="reindexing",
        total_chunks=1,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    db_session.add(DocumentChunk(doc_id=doc.id, chunk_index=0, pinecone_id="old-vec-0"))
    await db_session.commit()

    deleted_vector_calls = []

    async def _fake_delete_vectors(org_id_arg, vector_ids):
        deleted_vector_calls.append(vector_ids)

    monkeypatch.setattr(processing, "delete_vectors", _fake_delete_vectors)
    monkeypatch.setattr(processing.s3, "download_bytes", _async_return(b"Updated policy content."))
    monkeypatch.setattr(processing, "embed_texts", _async_return([[0.1, 0.2]]))
    monkeypatch.setattr(processing, "upsert_chunks", _async_return(["new-vec-0"]))

    await processing.reindex_document(str(doc.id))

    assert deleted_vector_calls == [["old-vec-0"]]

    await db_session.refresh(doc)
    assert doc.processing_status == "indexed"
    assert doc.total_chunks == 1

    result = await db_session.execute(select(DocumentChunk).where(DocumentChunk.doc_id == doc.id))
    chunks = result.scalars().all()
    assert [c.pinecone_id for c in chunks] == ["new-vec-0"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner
