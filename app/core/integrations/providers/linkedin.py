import httpx
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from app.config import settings

LINKEDIN_SCOPES = ["openid", "profile", "email", "w_member_social"]

def get_auth_url(state: str) -> str:
    """Build LinkedIn OAuth 2.0 URL."""
    base_url = "https://www.linkedin.com/oauth/v2/authorization"
    params = {
        "response_type": "code",
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "redirect_uri": f"{settings.APP_BASE_URL}/api/v1/integrations/linkedin/callback",
        "state": state,
        "scope": " ".join(LINKEDIN_SCOPES)
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base_url}?{query}"

async def exchange_code(code: str) -> Dict[str, Any]:
    """Exchange OAuth code for access token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{settings.APP_BASE_URL}/api/v1/integrations/linkedin/callback",
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET.get_secret_value()
            }
        )
        data = response.json()
        if response.status_code != 200:
            raise Exception(f"LinkedIn OAuth error: {data.get('error_description', data.get('error'))}")
        
        expires_in = data.get("expires_in", 5184000) # 60 days
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        return {
            "access_token": data["access_token"],
            "expires_at": expires_at,
            "scopes": data.get("scope", "")
        }

async def validate_token(access_token: str) -> bool:
    """Validate LinkedIn access token."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        return response.status_code == 200
