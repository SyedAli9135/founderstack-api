import httpx
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from app.config import settings

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file"
]

def get_auth_url(state: str) -> str:
    """Build Google OAuth URL."""
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": f"{settings.APP_BASE_URL}/api/v1/integrations/google_drive/callback",
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base_url}?{query}"

async def exchange_code(code: str) -> Dict[str, Any]:
    """Exchange OAuth code for access and refresh tokens."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
                "code": code,
                "redirect_uri": f"{settings.APP_BASE_URL}/api/v1/integrations/google_drive/callback",
                "grant_type": "authorization_code"
            }
        )
        data = response.json()
        if response.status_code != 200:
            raise Exception(f"Google OAuth error: {data.get('error_description', data.get('error'))}")
        
        expires_in = data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_at": expires_at,
            "scopes": data.get("scope", "")
        }

async def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """Refresh Google access token using refresh token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            }
        )
        data = response.json()
        if response.status_code != 200:
            raise Exception(f"Google Token Refresh error: {data.get('error_description', data.get('error'))}")
        
        expires_in = data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        return {
            "access_token": data["access_token"],
            "expires_at": expires_at
        }

async def revoke_token(token: str) -> bool:
    """Revoke Google token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://oauth2.googleapis.com/revoke?token={token}"
        )
        return response.status_code == 200

async def validate_token(access_token: str) -> bool:
    """Validate Google access token."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://www.googleapis.com/drive/v3/about?fields=user",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        return response.status_code == 200
