import pytest
from svix.webhooks import Webhook
from datetime import datetime, timezone
import json
import uuid
from sqlalchemy import select
from app.models import Organization, User
from app.config import settings


@pytest.mark.asyncio
async def test_clerk_webhook_org_created(client, db_session):
    """Test that a valid organization.created webhook successfully inserts a record."""
    # valid base64 secret after 'whsec_'
    # Use secret from settings (.env) or a fallback for testing
    secret = settings.CLERK_WEBHOOK_SECRET or "whsec_test_secret_fallback"

    payload = {
        "type": "organization.created",
        "data": {
            "id": "clerk_org_123",
            "name": "Acme Corp",
            "slug": "acme-corp"
        }
    }
    payload_str = json.dumps(payload, separators=(',', ':'))
    wh = Webhook(secret)
    # Generate valid signature
    timestamp = datetime.now(timezone.utc)
    signature = wh.sign("msg_001", timestamp, payload_str)
    headers = {
        "svix-id": "msg_001",
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature
    }

    response = await client.post("/api/webhooks/clerk", content=payload_str, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Verify the organization was actually created in the test DB
    stmt = select(Organization).where(
        Organization.clerk_org_id == "clerk_org_123")
    res = await db_session.execute(stmt)
    org = res.scalar_one_or_none()

    assert org is not None
    assert org.name == "Acme Corp"
    assert org.slug == "acme-corp"


@pytest.mark.asyncio
async def test_clerk_webhook_race_condition(client):
    """Test that membership creation fails with 422 if the organization doesn't exist yet."""
    # Use secret from settings
    secret = settings.CLERK_WEBHOOK_SECRET or "whsec_test_secret_fallback"

    payload = {
        "type": "organizationMembership.created",
        "data": {
            "organization": {"id": "non_existent_org"},
            "public_user_data": {
                "user_id": "user_123",
                "identifier": "test@test.com",
                "first_name": "Test",
                "last_name": "User"
            },
            "role": "admin"
        }
    }
    payload_str = json.dumps(payload, separators=(',', ':'))
    wh = Webhook(secret)
    timestamp = datetime.now(timezone.utc)
    signature = wh.sign("msg_002", timestamp, payload_str)
    headers = {
        "svix-id": "msg_002",
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature
    }

    response = await client.post("/api/webhooks/clerk", content=payload_str, headers=headers)

    # Our refined logic should return 422 to trigger a Clerk retry
    assert response.status_code == 422
    assert "Organization not found yet" in response.json()["detail"]


@pytest.mark.asyncio
async def test_clerk_webhook_invalid_signature(client):
    """Test that the webhook handler rejects invalid svix signatures."""
    settings.CLERK_WEBHOOK_SECRET = "whsec_valid_secret"

    payload = {"type": "test.event", "data": {}}
    payload_str = json.dumps(payload, separators=(',', ':'))
    headers = {
        "svix-id": "msg_003",
        "svix-timestamp": str(int(datetime.now().timestamp())),
        "svix-signature": "v1,YmFzZTY0"  # Valid base64 for "base64"
    }

    response = await client.post("/api/webhooks/clerk", content=payload_str, headers=headers)

    assert response.status_code == 400
    assert "Invalid signature" in response.json()["detail"]


@pytest.mark.asyncio
async def test_clerk_webhook_user_updated(client, db_session):
    """Test that user.updated correctly modifies name and avatar."""
    # 1. Setup: Create user
    from sqlalchemy import insert
    org_id = uuid.uuid4()
    await db_session.execute(insert(Organization).values(id=org_id, clerk_org_id="org_upd", name="Upd Org", slug="upd-org"))
    await db_session.execute(insert(User).values(
        org_id=org_id,
        clerk_user_id="user_upd_123",
        email="upd@test.com",
        full_name="Old Name",
        role="admin"
    ))
    await db_session.commit()

    secret = settings.CLERK_WEBHOOK_SECRET or "whsec_MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0"
    
    payload = {
        "type": "user.updated",
        "data": {
            "id": "user_upd_123",
            "first_name": "New",
            "last_name": "Name",
            "image_url": "https://example.com/avatar.jpg"
        }
    }
    payload_str = json.dumps(payload, separators=(',', ':'))
    wh = Webhook(secret)
    timestamp = datetime.now(timezone.utc)
    signature = wh.sign("msg_upd", timestamp, payload_str)
    headers = {"svix-id": "msg_upd", "svix-timestamp": str(
        int(timestamp.timestamp())), "svix-signature": signature}

    response = await client.post("/api/webhooks/clerk", content=payload_str, headers=headers)
    assert response.status_code == 200

    # Verify
    res = await db_session.execute(select(User).where(User.clerk_user_id == "user_upd_123"))
    user = res.scalar_one()
    assert user.full_name == "New Name"
    assert user.avatar_url == "https://example.com/avatar.jpg"


@pytest.mark.asyncio
async def test_clerk_webhook_org_deleted(client, db_session):
    """Test that organization.deleted hard-deletes the record."""
    # 1. Setup
    from sqlalchemy import insert
    await db_session.execute(insert(Organization).values(clerk_org_id="org_del", name="Del Org", slug="del-org"))
    await db_session.commit()

    secret = settings.CLERK_WEBHOOK_SECRET or "whsec_MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0"

    payload = {"type": "organization.deleted", "data": {"id": "org_del"}}
    payload_str = json.dumps(payload, separators=(',', ':'))
    wh = Webhook(secret)
    timestamp = datetime.now(timezone.utc)
    signature = wh.sign("msg_del", timestamp, payload_str)
    headers = {"svix-id": "msg_del", "svix-timestamp": str(
        int(timestamp.timestamp())), "svix-signature": signature}

    response = await client.post("/api/webhooks/clerk", content=payload_str, headers=headers)
    assert response.status_code == 200

    # Verify
    res = await db_session.execute(select(Organization).where(Organization.clerk_org_id == "org_del"))
    assert res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_clerk_webhook_membership_deleted(client, db_session):
    """Test that organizationMembership.deleted hard-deletes the user record."""
    # 1. Setup
    from sqlalchemy import insert
    org_id = uuid.uuid4()
    await db_session.execute(insert(Organization).values(id=org_id, clerk_org_id="org_mem_del", name="Mem Del Org", slug="mem-del-org"))
    await db_session.execute(insert(User).values(org_id=org_id, clerk_user_id="user_mem_del", email="del@test.com", full_name="Del Me"))
    await db_session.commit()

    secret = settings.CLERK_WEBHOOK_SECRET or "whsec_MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0"

    payload = {
        "type": "organizationMembership.deleted",
        "data": {
            "public_user_data": {"user_id": "user_mem_del"}
        }
    }
    payload_str = json.dumps(payload, separators=(',', ':'))
    wh = Webhook(secret)
    timestamp = datetime.now(timezone.utc)
    signature = wh.sign("msg_mem_del", timestamp, payload_str)
    headers = {"svix-id": "msg_mem_del", "svix-timestamp": str(
        int(timestamp.timestamp())), "svix-signature": signature}

    response = await client.post("/api/webhooks/clerk", content=payload_str, headers=headers)
    assert response.status_code == 200

    # Verify
    res = await db_session.execute(select(User).where(User.clerk_user_id == "user_mem_del"))
    assert res.scalar_one_or_none() is None
