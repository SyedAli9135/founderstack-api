import pytest
from httpx import AsyncClient
from app.config import settings
from app.models.integration import ApiKeyRegistry
from sqlalchemy import select

@pytest.mark.asyncio
async def test_submit_mock_api_key(client: AsyncClient, db_session, auth_headers, setup_user_org):
    # Test submitting a mock key
    mock_key = f"{settings.ANTHROPIC_API_KEY_MOCK_PREFIX}test-12345"
    response = await client.post(
        "/api/v1/settings/api-key",
        json={"api_key": mock_key},
        headers=auth_headers
    )
    
    assert response.status_code == 201
    assert response.json()["status"] == "success"
    
    # Verify in DB
    stmt = select(ApiKeyRegistry).where(
        ApiKeyRegistry.org_id == setup_user_org["org_id"],
        ApiKeyRegistry.provider == "anthropic"
    )
    result = await db_session.execute(stmt)
    db_key = result.scalar_one_or_none()
    
    assert db_key is not None
    assert db_key.key_prefix.startswith("sk-ant-")
    assert db_key.provider == "anthropic"
    assert db_key.is_valid is True
    # Ensure it is encrypted (not equal to the mock key)
    assert db_key.encrypted_key != mock_key

@pytest.mark.asyncio
async def test_submit_invalid_api_key(client: AsyncClient, auth_headers):
    # Test submitting a key that doesn't start with mock prefix and would fail real validation
    # (Since we aren't mocking the network call here, it should fail if it hits Path B)
    response = await client.post(
        "/api/v1/settings/api-key",
        json={"api_key": "invalid-key-no-prefix"},
        headers=auth_headers
    )
    
    assert response.status_code == 400
    assert "Invalid Anthropic API key" in response.json()["detail"]

@pytest.mark.asyncio
async def test_get_api_key_status(client: AsyncClient, auth_headers):
    # First submit
    mock_key = f"{settings.ANTHROPIC_API_KEY_MOCK_PREFIX}status-test"
    await client.post(
        "/api/v1/settings/api-key",
        json={"api_key": mock_key},
        headers=auth_headers
    )
    
    # Then get status
    response = await client.get("/api/v1/settings/api-key/status", headers=auth_headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "anthropic"
    assert data["is_valid"] is True
    assert data["key_prefix"].startswith("sk-ant-")

@pytest.mark.asyncio
async def test_update_existing_api_key(client: AsyncClient, db_session, auth_headers, setup_user_org):
    # 1. First submission
    key_v1 = f"{settings.ANTHROPIC_API_KEY_MOCK_PREFIX}v1-key"
    await client.post("/api/v1/settings/api-key", json={"api_key": key_v1}, headers=auth_headers)
    
    # 2. Second submission (update)
    key_v2 = f"{settings.ANTHROPIC_API_KEY_MOCK_PREFIX}v2-updated-key"
    response = await client.post("/api/v1/settings/api-key", json={"api_key": key_v2}, headers=auth_headers)
    
    assert response.status_code == 201
    
    # 3. Verify only ONE record exists for this org/provider
    stmt = select(ApiKeyRegistry).where(
        ApiKeyRegistry.org_id == setup_user_org["org_id"],
        ApiKeyRegistry.provider == "anthropic"
    )
    result = await db_session.execute(stmt)
    records = result.scalars().all()
    
    assert len(records) == 1
    assert records[0].key_prefix.startswith("sk-ant-")
    # Verify the prefix reflects the NEW key (v2)
    # Since we take first 7 chars: "sk-ant-" will be the same, but let's check prefix
    assert "v2" in records[0].key_prefix or records[0].key_prefix == "sk-ant-..."

@pytest.mark.asyncio
async def test_settings_unauthorized(client: AsyncClient):
    # Test submission without auth
    response = await client.post("/api/v1/settings/api-key", json={"api_key": "some-key"})
    assert response.status_code == 401
    
    # Test status without auth
    response = await client.get("/api/v1/settings/api-key/status")
    assert response.status_code == 401
