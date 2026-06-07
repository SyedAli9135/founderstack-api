import httpx
import base64
from typing import Dict, Any
from app.config import settings

def get_auth_url(state: str) -> str:
    """Build Notion OAuth URL."""
    base_url = "https://api.notion.com/v1/oauth/authorize"
    params = {
        "client_id": settings.NOTION_CLIENT_ID,
        "response_type": "code",
        "owner": "user",
        "redirect_uri": f"{settings.APP_BASE_URL}/api/v1/integrations/notion/callback",
        "state": state
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base_url}?{query}"

async def exchange_code(code: str) -> Dict[str, Any]:
    """Exchange OAuth code for access token."""
    auth_header = base64.b64encode(
        f"{settings.NOTION_CLIENT_ID}:{settings.NOTION_CLIENT_SECRET.get_secret_value()}".encode()
    ).decode()
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.notion.com/v1/oauth/token",
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/json"
            },
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{settings.APP_BASE_URL}/api/v1/integrations/notion/callback"
            }
        )
        data = response.json()
        if response.status_code != 200:
            raise Exception(f"Notion OAuth error: {data.get('error_description', data.get('error'))}")
        
        return {
            "access_token": data["access_token"],
            "workspace_id": data.get("workspace_id"),
            "workspace_name": data.get("workspace_name"),
            "bot_id": data.get("bot_id")
        }

async def validate_token(access_token: str) -> bool:
    """Validate Notion access token."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.notion.com/v1/users/me",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Notion-Version": "2022-06-28"
            }
        )
        return response.status_code == 200
