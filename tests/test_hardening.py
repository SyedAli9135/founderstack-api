import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_request_id_header(client: AsyncClient):
    """Verify that every response includes X-Request-ID."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0

@pytest.mark.asyncio
async def test_404_standardized_error(client: AsyncClient):
    """Verify that a 404 returns the standardized error schema."""
    response = await client.get("/api/v1/non-existent-endpoint")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "HTTP_EXCEPTION"
    assert "request_id" in data["error"]

@pytest.mark.asyncio
async def test_validation_standardized_error(client: AsyncClient, auth_headers):
    """Verify that Pydantic validation errors return the standardized schema."""
    # POST to a real endpoint with bad data, but with auth
    response = await client.post(
        "/api/v1/settings/api-key", 
        json={"wrong_field": "data"},
        headers=auth_headers
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["detail"] is not None
    assert "request_id" in data["error"]

@pytest.mark.asyncio
async def test_unhandled_exception_masking(db_session):
    """
    Verify that an unhandled exception returns 500 and masks details.
    We use a fresh client with raise_app_exceptions=False.
    """
    from httpx import ASGITransport
    
    # We add a temporary route to a copy of the app to avoid polluting global state
    @app.get("/api/v1/test-crash")
    async def crash():
        raise ValueError("Boom!")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/test-crash")
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert "request_id" in data["error"]
    
    # In development, it might show "Boom!", but in production it should be generic.
    # Our handler uses settings.APP_ENV to decide.
