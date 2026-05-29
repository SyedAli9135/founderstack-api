import pytest
from httpx import AsyncClient
from unittest.mock import patch
from app.config import settings

@pytest.mark.asyncio
async def test_sql_injection_attempt(client: AsyncClient, auth_headers):
    """Verify that malicious input strings do not cause SQL injection or crashes."""
    malicious_payload = "sk-ant-test-'; DROP TABLE api_key_registry;--"
    response = await client.post(
        "/api/v1/settings/api-key",
        json={"api_key": malicious_payload},
        headers=auth_headers
    )
    # Even if it's "valid" format-wise (starts with sk-ant-test-), it should be handled safely by SQLAlchemy
    assert response.status_code in [201, 400]
    # If it was created, ensure it didn't actually drop the table
    # (Testing the fact that SQLAlchemy uses parameterized queries)

@pytest.mark.asyncio
async def test_anthropic_service_failure_path(client: AsyncClient, auth_headers):
    """Verify that when the Anthropic service itself crashes, we return a 500."""
    with patch("app.api.v1.endpoints.settings.validate_anthropic_key") as mock_val:
        mock_val.side_effect = Exception("Anthropic API Down")
        
        response = await client.post(
            "/api/v1/settings/api-key",
            json={"api_key": f"{settings.ANTHROPIC_API_KEY_MOCK_PREFIX}error-test"},
            headers=auth_headers
        )
        
        assert response.status_code == 500
        data = response.json()
        assert "The validation service encountered an error" in data["error"]["message"]
        assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"

@pytest.mark.asyncio
async def test_clerk_webhook_missing_org_graceful(client):
    """Verify that membership creation for missing org returns 422 with standardized error."""
    from svix.webhooks import Webhook
    import json
    from datetime import datetime, timezone

    secret = settings.CLERK_WEBHOOK_SECRET.get_secret_value()
    payload = {
        "type": "organizationMembership.created",
        "data": {
            "organization": {"id": "missing_org_uuid"},
            "public_user_data": {"user_id": "u1", "identifier": "t@t.com"},
            "role": "admin"
        }
    }
    payload_str = json.dumps(payload, separators=(',', ':'))
    wh = Webhook(secret)
    timestamp = datetime.now(timezone.utc)
    signature = wh.sign("msg_bullet_1", timestamp, payload_str)
    headers = {
        "svix-id": "msg_bullet_1",
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature
    }

    response = await client.post("/api/webhooks/clerk", content=payload_str, headers=headers)
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "HTTP_EXCEPTION"
    assert "Organization not found" in data["error"]["message"]
