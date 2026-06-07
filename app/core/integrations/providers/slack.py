import httpx
from typing import Dict, Any
from app.config import settings

SLACK_SCOPES = [
    "chat:write",
    "chat:write.public",
    "channels:read",
    "channels:history",
    "im:write",
    "users:read",
    "users:read.email"
]

def get_auth_url(state: str) -> str:
    """Build Slack OAuth v2 URL."""
    base_url = "https://slack.com/oauth/v2/authorize"
    params = {
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": " ".join(SLACK_SCOPES),
        "redirect_uri": f"{settings.APP_BASE_URL}/api/v1/integrations/slack/callback",
        "state": state
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base_url}?{query}"

async def exchange_code(code: str) -> Dict[str, Any]:
    """Exchange OAuth code for access token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": settings.SLACK_CLIENT_ID,
                "client_secret": settings.SLACK_CLIENT_SECRET.get_secret_value(),
                "code": code,
                "redirect_uri": f"{settings.APP_BASE_URL}/api/v1/integrations/slack/callback"
            }
        )
        data = response.json()
        if not data.get("ok"):
            raise Exception(f"Slack OAuth error: {data.get('error')}")
        
        return {
            "access_token": data["access_token"],
            "team_id": data["team"]["id"],
            "bot_user_id": data["bot_user_id"],
            "scopes": data.get("scope", "")
        }

async def revoke_token(access_token: str) -> bool:
    """Revoke Slack access token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://slack.com/api/auth.revoke",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        data = response.json()
        return data.get("ok", False)

async def validate_token(access_token: str) -> bool:
    """Validate Slack access token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        data = response.json()
        return data.get("ok", False)
