from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.integrations.catalog import INTEGRATIONS
from app.core.integrations.state import generate_state, verify_state
from app.core.integrations.token_store import save_connection, get_connection
from app.core.integrations.providers import slack, notion, google_drive, stripe, github, linkedin
from app.models.integration import MCPConnection
from app.models.identity import User
from app.config import settings
from app.api.v1.schemas.base import SuccessEnvelope

router = APIRouter()

PROVIDERS = {
    "slack": slack,
    "notion": notion,
    "google_drive": google_drive,
    "stripe": stripe,
    "github": github,
    "linkedin": linkedin
}


@router.get("/", response_model=SuccessEnvelope[List[dict]])
async def list_integrations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all supported integrations and their connection status."""
    # Fetch all connections for this org
    stmt = select(MCPConnection).where(
        MCPConnection.org_id == current_user.org_id)
    result = await db.execute(stmt)
    connections = {c.service_name: c for c in result.scalars().all()}

    response = []
    for service, info in INTEGRATIONS.items():
        conn = connections.get(service)
        response.append({
            "service": service,
            "name": info["name"],
            "category": info["category"],
            "auth_type": info["auth_type"],
            "status": conn.oauth_status if conn and conn.is_active else "not_connected",
            "connected_at": conn.created_at if conn and conn.is_active else None,
            "scopes": conn.oauth_scopes if conn and conn.is_active else []
        })
    return SuccessEnvelope(data=response)


@router.post("/{service}/connect")
async def connect_integration(
    service: str,
    key_data: Optional[dict] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Unified endpoint to connect a service.
    - For OAuth: Returns a redirect URL.
    - For API Key/PAT: Validates and saves the key.
    """
    if service not in INTEGRATIONS:
        raise HTTPException(status_code=400, detail="Invalid service")

    auth_type = INTEGRATIONS[service]["auth_type"]
    provider = PROVIDERS.get(service)

    if not provider:
        raise HTTPException(status_code=501, detail="Provider not implemented")

    # 1. Handle OAuth Flow
    if auth_type == "oauth":
        state = await generate_state(str(current_user.org_id), service)
        return SuccessEnvelope(data={"redirect_url": provider.get_auth_url(state)})

    # 2. Handle API Key / PAT Flow
    if auth_type in ["api_key", "pat"]:
        api_key = key_data.get("key") if key_data else None
        if not api_key:
            raise HTTPException(status_code=400, detail="Key is required for this service")

        is_valid = await provider.validate_token(api_key)
        if not is_valid:
            raise HTTPException(status_code=400, detail="Invalid API key or token")

        await save_connection(
            db=db,
            org_id=str(current_user.org_id),
            service=service,
            access_token=api_key
        )
        return SuccessEnvelope(data={"status": "connected"})

    raise HTTPException(status_code=400, detail="Unsupported auth type")


@router.get("/{service}/callback")
async def oauth_callback(
    service: str,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
):
    """OAuth callback endpoint."""
    org_id, state_service, extra_data = await verify_state(state)
    if state_service != service:
        raise HTTPException(status_code=400, detail="State service mismatch")

    provider = PROVIDERS.get(service)
    if not provider:
        raise HTTPException(status_code=501, detail="Provider not implemented")

    try:
        token_data = await provider.exchange_code(code)

        await save_connection(
            db=db,
            org_id=org_id,
            service=service,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=token_data.get("expires_at"),
            scopes=token_data.get("scopes", "").split(",") if isinstance(
                token_data.get("scopes"), str) else token_data.get("scopes", [])
        )

        # Redirect back to frontend
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/integrations?connected={service}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{service}", response_model=SuccessEnvelope[dict])
async def disconnect_integration(
    service: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Disconnect an integration."""
    stmt = update(MCPConnection).where(
        MCPConnection.org_id == current_user.org_id,
        MCPConnection.service_name == service
    ).values(is_active=False, oauth_status='revoked')

    await db.execute(stmt)
    await db.commit()
    return SuccessEnvelope(data={"status": "disconnected"})


@router.get("/{service}/status", response_model=SuccessEnvelope[dict])
async def get_integration_status(
    service: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Check the health/status of a connection."""
    conn_data = await get_connection(db, str(current_user.org_id), service)
    if not conn_data:
        return SuccessEnvelope(data={"status": "not_connected"})

    provider = PROVIDERS.get(service)
    if not provider:
        return SuccessEnvelope(data={"status": "unknown"})

    is_valid = await provider.validate_token(conn_data["access_token"])
    if is_valid:
        return SuccessEnvelope(data={"status": "connected"})

    # Attempt refresh if possible
    if conn_data.get("refresh_token") and hasattr(provider, "refresh_access_token"):
        try:
            new_tokens = await provider.refresh_access_token(conn_data["refresh_token"])
            await save_connection(
                db=db,
                org_id=str(current_user.org_id),
                service=service,
                access_token=new_tokens["access_token"],
                refresh_token=new_tokens.get(
                    "refresh_token", conn_data["refresh_token"]),
                expires_at=new_tokens.get("expires_at")
            )
            return SuccessEnvelope(data={"status": "connected"})
        except:
            pass

    return SuccessEnvelope(data={"status": "expired"})
