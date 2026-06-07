import json
from datetime import datetime
from typing import Optional, Dict
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.integration import MCPConnection
from app.core.exceptions import ToolAuthExpiredError

def _get_fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.get_secret_value().encode())

def encrypt_token(plaintext: str) -> str:
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()

def decrypt_token(ciphertext: str) -> str:
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()

async def save_connection(
    db: AsyncSession,
    org_id: str,
    service: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    scopes: Optional[list] = None
):
    """Save or update an MCP connection with encrypted credentials."""
    credentials = {
        "access_token": access_token,
        "refresh_token": refresh_token
    }
    encrypted_creds = encrypt_token(json.dumps(credentials))
    
    # Check if exists
    stmt = select(MCPConnection).where(
        MCPConnection.org_id == org_id,
        MCPConnection.service_name == service
    )
    result = await db.execute(stmt)
    connection = result.scalar_one_or_none()
    
    if connection:
        connection.encrypted_credentials = encrypted_creds
        connection.oauth_status = 'connected'
        connection.oauth_scopes = scopes or []
        connection.token_expires_at = expires_at
        connection.is_active = True
    else:
        connection = MCPConnection(
            org_id=org_id,
            service_name=service,
            encrypted_credentials=encrypted_creds,
            oauth_status='connected',
            oauth_scopes=scopes or [],
            token_expires_at=expires_at,
            is_active=True
        )
        db.add(connection)
    
    await db.commit()

async def get_connection(
    db: AsyncSession,
    org_id: str,
    service: str
) -> Optional[Dict]:
    """Retrieve and decrypt connection credentials."""
    stmt = select(MCPConnection).where(
        MCPConnection.org_id == org_id,
        MCPConnection.service_name == service,
        MCPConnection.is_active == True
    )
    result = await db.execute(stmt)
    connection = result.scalar_one_or_none()
    
    if not connection or not connection.encrypted_credentials:
        return None
    
    try:
        creds_json = decrypt_token(connection.encrypted_credentials)
        creds = json.loads(creds_json)
        return {
            "access_token": creds.get("access_token"),
            "refresh_token": creds.get("refresh_token"),
            "expires_at": connection.token_expires_at,
            "scopes": connection.oauth_scopes,
            "status": connection.oauth_status
        }
    except Exception:
        return None

async def get_integration_token(db: AsyncSession, org_id: str, service: str) -> str:
    """
    Retrieve and decrypt access token for a service.
    Raises ToolAuthExpiredError if not connected or expired.
    """
    conn_data = await get_connection(db, org_id, service)
    if not conn_data or conn_data["status"] != "connected":
        raise ToolAuthExpiredError(service)
    
    return conn_data["access_token"]
