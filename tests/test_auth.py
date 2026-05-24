import pytest
import jwt
import uuid
from sqlalchemy import insert
from app.models import User, Organization
from app.config import settings

@pytest.mark.asyncio
async def test_get_me_authenticated(client, db_session):
    """Test that the /me endpoint returns the correct user and org data for a valid token."""
    # 1. Setup: Create test organization and user
    org_id = uuid.uuid4()
    await db_session.execute(
        insert(Organization).values(
            id=org_id,
            name="Testing HQ",
            slug="testing-hq",
            clerk_org_id="org_auth_123"
        )
    )
    
    user_id = uuid.uuid4()
    await db_session.execute(
        insert(User).values(
            id=user_id,
            org_id=org_id,
            clerk_user_id="user_auth_123",
            email="tester@founderstack.ai",
            full_name="Tester McTest",
            role="admin"
        )
    )
    await db_session.commit()

    # 2. Mock a JWT (we decode without verification in our current get_current_user logic)
    token = jwt.encode({"sub": "user_auth_123"}, "dummy_secret", algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3. Execution
    response = await client.get("/api/v1/auth/me", headers=headers)
    
    # 4. Verification
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "tester@founderstack.ai"
    assert data["user"]["role"] == "admin"
    assert data["organization"]["slug"] == "testing-hq"

@pytest.mark.asyncio
async def test_get_me_unauthorized(client):
    """Test that requests without a Bearer token are rejected."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code in [401, 403]

@pytest.mark.asyncio
async def test_get_me_user_not_found(client):
    """Test that a valid JWT pointing to a non-existent internal user returns 401."""
    token = jwt.encode({"sub": "ghost_id_404"}, "dummy_secret", algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    
    response = await client.get("/api/v1/auth/me", headers=headers)
    
    assert response.status_code == 401
    assert "User profile not synchronized" in response.json()["detail"]
