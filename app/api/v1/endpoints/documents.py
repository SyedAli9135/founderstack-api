import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.base import SuccessEnvelope
from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.documents import processing
from app.core.storage import s3
from app.models.identity import User
from app.models.knowledge import Document

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"legal", "finance", "hr", "technical", "marketing", "operations", "general"}


class DocumentSummary(BaseModel):
    id: uuid.UUID
    filename: str
    category: str
    processing_status: str
    total_chunks: int
    byte_size: Optional[int] = None
    created_at: datetime
    indexed_at: Optional[datetime] = None


class DocumentDetail(DocumentSummary):
    mime_type: Optional[str] = None
    error_detail: Optional[str] = None


def _to_summary(doc: Document) -> DocumentSummary:
    return DocumentSummary(
        id=doc.id,
        filename=doc.filename,
        category=doc.category or "general",
        processing_status=doc.processing_status,
        total_chunks=doc.total_chunks or 0,
        byte_size=doc.byte_size,
        created_at=doc.created_at,
        indexed_at=doc.indexed_at,
    )


def _to_detail(doc: Document) -> DocumentDetail:
    return DocumentDetail(
        **_to_summary(doc).model_dump(),
        mime_type=doc.mime_type,
        error_detail=doc.error_detail,
    )


async def _get_org_document(db: AsyncSession, doc_id: uuid.UUID, org_id) -> Document:
    stmt = select(Document).where(Document.id == doc_id, Document.org_id == org_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form("general"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document (PDF/DOCX/TXT/MD, up to 50MB) and kick off background RAG indexing."""
    ext = processing.get_extension(file.filename or "")
    if ext not in processing.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(processing.ALLOWED_EXTENSIONS))}",
        )
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category '{category}'. Allowed: {', '.join(sorted(VALID_CATEGORIES))}",
        )

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    if len(data) > processing.MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds the 50MB size limit")

    doc = Document(
        org_id=current_user.org_id,
        filename=file.filename,
        s3_path="",  # filled in once the doc id (used in the S3 key) is assigned
        mime_type=processing.ALLOWED_EXTENSIONS[ext],
        byte_size=len(data),
        category=category,
        processing_status="pending",
        uploaded_by=current_user.id,
    )
    db.add(doc)
    await db.flush()

    s3_key = f"documents/{current_user.org_id}/{doc.id}/{file.filename}"
    doc.s3_path = s3_key
    await s3.upload_bytes(s3_key, data, content_type=processing.ALLOWED_EXTENSIONS[ext])
    await db.commit()

    asyncio.create_task(processing.process_document(str(doc.id)))

    return SuccessEnvelope(
        message="Document uploaded. Indexing has started.",
        data={"doc_id": str(doc.id), "status": "processing"},
    )


@router.get("/", response_model=SuccessEnvelope[List[DocumentSummary]])
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all documents uploaded by the current org, newest first."""
    stmt = (
        select(Document)
        .where(Document.org_id == current_user.org_id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()
    return SuccessEnvelope(data=[_to_summary(d) for d in docs])


@router.get("/{doc_id}", response_model=SuccessEnvelope[DocumentDetail])
async def get_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single document's detail, including processing status, chunk count, and any error."""
    doc = await _get_org_document(db, doc_id, current_user.org_id)
    return SuccessEnvelope(data=_to_detail(doc))


@router.delete("/{doc_id}", response_model=SuccessEnvelope[dict])
async def delete_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a document and enqueue background purge of its Pinecone vectors + S3 file."""
    doc = await _get_org_document(db, doc_id, current_user.org_id)
    doc.processing_status = "deleting"
    await db.commit()

    asyncio.create_task(processing.purge_document_job(str(doc.id)))

    return SuccessEnvelope(data={"status": "deleting"})


@router.post("/{doc_id}/reindex", response_model=SuccessEnvelope[dict])
async def reindex_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-embed a document with the latest embedding model/version."""
    doc = await _get_org_document(db, doc_id, current_user.org_id)
    if doc.processing_status in ("processing", "deleting", "reindexing"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is currently {doc.processing_status}",
        )

    doc.processing_status = "reindexing"
    await db.commit()

    asyncio.create_task(processing.reindex_document(str(doc.id)))

    return SuccessEnvelope(data={"status": "reindexing"})
