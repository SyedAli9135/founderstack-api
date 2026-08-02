"""
Endpoint tests for the Workflow 6 documents API (app/api/v1/endpoints/documents.py).

Follows the pattern from test_settings.py: real HTTP calls through the `client`
fixture against the isolated test DB. The document ingestion pipeline itself
(app/core/documents/processing.py) is unit-tested separately in
test_documents_processing.py, so here `processing.process_document`,
`processing.purge_document_job`, `processing.reindex_document`, and
`s3.upload_bytes` are monkeypatched to lightweight fakes — these tests only
verify request validation, DB state, org scoping, and that the right
background task gets scheduled with the right arguments.
"""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select

import app.api.v1.endpoints.documents as documents_endpoint
from app.models.identity import Organization
from app.models.knowledge import Document, DocumentChunk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def captured_tasks(monkeypatch):
    """Capture asyncio.create_task calls made by the documents router so tests can await them deterministically."""
    tasks = []
    real_create_task = asyncio.create_task

    def _capture(coro):
        task = real_create_task(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(documents_endpoint.asyncio, "create_task", _capture)
    return tasks


@pytest.fixture
def fake_pipeline(monkeypatch):
    """Replace the ingestion pipeline + S3 upload with no-op fakes that record their calls."""
    calls = {"process_document": [], "purge_document_job": [], "reindex_document": [], "upload_bytes": []}

    async def _process_document(doc_id):
        calls["process_document"].append(doc_id)

    async def _purge_document_job(doc_id):
        calls["purge_document_job"].append(doc_id)

    async def _reindex_document(doc_id):
        calls["reindex_document"].append(doc_id)

    async def _upload_bytes(key, data, content_type=None):
        calls["upload_bytes"].append((key, content_type))

    monkeypatch.setattr(documents_endpoint.processing, "process_document", _process_document)
    monkeypatch.setattr(documents_endpoint.processing, "purge_document_job", _purge_document_job)
    monkeypatch.setattr(documents_endpoint.processing, "reindex_document", _reindex_document)
    monkeypatch.setattr(documents_endpoint.s3, "upload_bytes", _upload_bytes)
    return calls


async def _upload(client, auth_headers, filename="handbook.txt", content=b"Company handbook body.", category="hr", content_type="text/plain"):
    return await client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, content, content_type)},
        data={"category": category},
        headers=auth_headers,
    )


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_rejects_unsupported_file_type(client: AsyncClient, auth_headers, fake_pipeline, captured_tasks):
    response = await _upload(client, auth_headers, filename="archive.zip", content_type="application/zip")
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_upload_rejects_invalid_category(client: AsyncClient, auth_headers, fake_pipeline, captured_tasks):
    response = await _upload(client, auth_headers, category="not-a-real-category")
    assert response.status_code == 400
    assert "Invalid category" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(client: AsyncClient, auth_headers, fake_pipeline, captured_tasks):
    response = await _upload(client, auth_headers, content=b"")
    assert response.status_code == 400
    assert "empty" in response.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(client: AsyncClient, auth_headers, fake_pipeline, captured_tasks, monkeypatch):
    monkeypatch.setattr(documents_endpoint.processing, "MAX_FILE_SIZE_BYTES", 10)
    response = await _upload(client, auth_headers, content=b"this is more than ten bytes")
    assert response.status_code == 400
    assert "50MB" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_upload_unauthorized(client: AsyncClient):
    response = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("f.txt", b"hi", "text/plain")},
        data={"category": "general"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Upload success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_success_creates_pending_document_and_schedules_processing(
    client: AsyncClient, db_session, auth_headers, setup_user_org, fake_pipeline, captured_tasks
):
    response = await _upload(client, auth_headers, filename="handbook.txt", content=b"Company handbook body.", category="hr")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "success"
    doc_id = body["data"]["doc_id"]
    assert body["data"]["status"] == "processing"

    await asyncio.gather(*captured_tasks)

    result = await db_session.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
    doc = result.scalar_one()
    assert doc.org_id == setup_user_org["org_id"]
    assert doc.filename == "handbook.txt"
    assert doc.category == "hr"
    assert doc.mime_type == "text/plain"
    assert doc.byte_size == len(b"Company handbook body.")
    assert doc.s3_path == f"documents/{setup_user_org['org_id']}/{doc.id}/handbook.txt"

    assert fake_pipeline["process_document"] == [doc_id]
    assert fake_pipeline["upload_bytes"] == [(doc.s3_path, "text/plain")]


@pytest.mark.asyncio
async def test_upload_defaults_category_to_general(client: AsyncClient, db_session, auth_headers, setup_user_org, fake_pipeline, captured_tasks):
    response = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("notes.md", b"# notes", "text/markdown")},
        headers=auth_headers,
    )
    assert response.status_code == 202
    doc_id = response.json()["data"]["doc_id"]

    result = await db_session.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
    doc = result.scalar_one()
    assert doc.category == "general"


# ---------------------------------------------------------------------------
# List / Get (org scoping)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_documents_only_returns_own_org(client: AsyncClient, db_session, auth_headers, setup_user_org):
    own_doc = Document(
        org_id=setup_user_org["org_id"], filename="mine.txt", s3_path="documents/mine/mine.txt",
        mime_type="text/plain", byte_size=5, category="general", processing_status="indexed", total_chunks=2,
    )
    db_session.add(own_doc)

    other_org_id = uuid.uuid4()
    await db_session.execute(
        insert(Organization).values(id=other_org_id, name="Other Org", slug="other-org", clerk_org_id="org_other_999")
    )
    other_doc = Document(
        org_id=other_org_id, filename="theirs.txt", s3_path="documents/theirs/theirs.txt",
        mime_type="text/plain", byte_size=5, category="general", processing_status="indexed",
    )
    db_session.add(other_doc)
    await db_session.commit()

    response = await client.get("/api/v1/documents/", headers=auth_headers)
    assert response.status_code == 200
    filenames = [d["filename"] for d in response.json()["data"]]
    assert filenames == ["mine.txt"]


@pytest.mark.asyncio
async def test_get_document_detail(client: AsyncClient, db_session, auth_headers, setup_user_org):
    doc = Document(
        org_id=setup_user_org["org_id"], filename="terms.pdf", s3_path="documents/x/terms.pdf",
        mime_type="application/pdf", byte_size=99, category="legal", processing_status="failed",
        error_detail="Extraction failed: corrupt file",
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    response = await client.get(f"/api/v1/documents/{doc.id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["filename"] == "terms.pdf"
    assert data["processing_status"] == "failed"
    assert data["error_detail"] == "Extraction failed: corrupt file"


@pytest.mark.asyncio
async def test_get_document_not_found_for_other_org(client: AsyncClient, db_session, auth_headers, setup_user_org):
    other_org_id = uuid.uuid4()
    await db_session.execute(
        insert(Organization).values(id=other_org_id, name="Other Org 2", slug="other-org-2", clerk_org_id="org_other_888")
    )
    other_doc = Document(
        org_id=other_org_id, filename="secret.txt", s3_path="documents/y/secret.txt",
        mime_type="text/plain", byte_size=5, category="general", processing_status="indexed",
    )
    db_session.add(other_doc)
    await db_session.commit()
    await db_session.refresh(other_doc)

    response = await client.get(f"/api/v1/documents/{other_doc.id}", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_document_not_found_for_unknown_id(client: AsyncClient, auth_headers, setup_user_org):
    response = await client.get(f"/api/v1/documents/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_document_marks_deleting_and_schedules_purge(
    client: AsyncClient, db_session, auth_headers, setup_user_org, fake_pipeline, captured_tasks
):
    doc = Document(
        org_id=setup_user_org["org_id"], filename="old.txt", s3_path="documents/z/old.txt",
        mime_type="text/plain", byte_size=5, category="general", processing_status="indexed",
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    response = await client.delete(f"/api/v1/documents/{doc.id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "deleting"

    await asyncio.gather(*captured_tasks)
    assert fake_pipeline["purge_document_job"] == [str(doc.id)]

    await db_session.refresh(doc)
    assert doc.processing_status == "deleting"


@pytest.mark.asyncio
async def test_delete_document_not_found(client: AsyncClient, auth_headers, setup_user_org):
    response = await client.delete(f"/api/v1/documents/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Reindex
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reindex_document_schedules_reindex(
    client: AsyncClient, db_session, auth_headers, setup_user_org, fake_pipeline, captured_tasks
):
    doc = Document(
        org_id=setup_user_org["org_id"], filename="policy.txt", s3_path="documents/w/policy.txt",
        mime_type="text/plain", byte_size=5, category="legal", processing_status="indexed", total_chunks=3,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    response = await client.post(f"/api/v1/documents/{doc.id}/reindex", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "reindexing"

    await asyncio.gather(*captured_tasks)
    assert fake_pipeline["reindex_document"] == [str(doc.id)]


@pytest.mark.asyncio
async def test_reindex_document_conflict_while_already_processing(client: AsyncClient, db_session, auth_headers, setup_user_org):
    doc = Document(
        org_id=setup_user_org["org_id"], filename="busy.txt", s3_path="documents/v/busy.txt",
        mime_type="text/plain", byte_size=5, category="general", processing_status="processing",
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    response = await client.post(f"/api/v1/documents/{doc.id}/reindex", headers=auth_headers)
    assert response.status_code == 409
