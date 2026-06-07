import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.models.integration import MCPConnection
from app.core.integrations.token_store import get_connection, save_connection
from app.core.integrations.providers import google_drive

logger = logging.getLogger(__name__)

# Providers that support refresh
REFRESH_PROVIDERS = {
    "google_drive": google_drive
}

async def refresh_all_expired_tokens():
    """Find and refresh all tokens nearing expiration."""
    async with AsyncSessionLocal() as db:
        # Find active connections with expiration in the next 10 minutes
        cutoff = datetime.now(timezone.utc) + timedelta(minutes=10)
        stmt = select(MCPConnection).where(
            MCPConnection.is_active == True,
            MCPConnection.token_expires_at <= cutoff,
            MCPConnection.service_name.in_(REFRESH_PROVIDERS.keys())
        )
        result = await db.execute(stmt)
        connections = result.scalars().all()
        
        for conn in connections:
            service = conn.service_name
            provider = REFRESH_PROVIDERS[service]
            
            logger.info(f"Refreshing token for {service} (org: {conn.org_id})")
            
            # Use get_connection to decrypt refresh_token
            conn_data = await get_connection(db, str(conn.org_id), service)
            if not conn_data or not conn_data.get("refresh_token"):
                logger.warning(f"No refresh token found for {service} (org: {conn.org_id})")
                continue
                
            try:
                new_tokens = await provider.refresh_access_token(conn_data["refresh_token"])
                await save_connection(
                    db=db,
                    org_id=str(conn.org_id),
                    service=service,
                    access_token=new_tokens["access_token"],
                    refresh_token=new_tokens.get("refresh_token", conn_data["refresh_token"]),
                    expires_at=new_tokens.get("expires_at"),
                    scopes=conn_data.get("scopes")
                )
                logger.info(f"Successfully refreshed {service} token")
            except Exception as e:
                logger.error(f"Failed to refresh {service} token: {str(e)}")
                # We could set status to 'expired' here if refresh fails repeatedly

async def start_refresh_job():
    """Background loop that runs the refresh job every 30 minutes."""
    while True:
        try:
            await refresh_all_expired_tokens()
        except Exception as e:
            logger.error(f"Error in refresh job loop: {str(e)}")
        
        await asyncio.sleep(1800) # 30 minutes
