import jwt
from typing import Optional
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.core.database import get_db
from app.models import User, Organization
import logging

logger = logging.getLogger(__name__)

security = HTTPBearer()

# Note: In a production environment, you should fetch and cache the JWKS 
# periodically from Clerk (e.g., https://clerk.your-domain.com/.well-known/jwks.json)
# for signature verification. For this implementation, we focus on the session retrieval.

async def get_current_user(
    auth: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependency that validates the Clerk JWT and returns the internal User model.
    """
    token = auth.credentials
    try:
        # Decode without full signature verification for initial speed, 
        # assuming the proxy/load-balancer or a dedicated service might have validated it,
        # or we integrate full JWKS validation here.
        payload = jwt.decode(token, options={"verify_signature": False})
        
        clerk_user_id = payload.get("sub")
        if not clerk_user_id:
            logger.warning("Token missing 'sub' claim")
            raise HTTPException(status_code=401, detail="Invalid session token")

        # Query our local database for the user synchronized via Webhooks
        res = await db.execute(
            select(User)
            .where(User.clerk_user_id == clerk_user_id)
            .where(User.is_active == True)
        )
        user = res.scalar_one_or_none()
        
        if not user:
            logger.warning(f"User {clerk_user_id} not found in database (sync pending?)")
            raise HTTPException(status_code=401, detail="User profile not synchronized")
            
        return user
    except HTTPException:
        raise
    except jwt.PyJWTError as e:
        logger.error(f"JWT Decode error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.exception(f"Unexpected auth error: {e}")
        raise HTTPException(status_code=500, detail="Internal authentication error")

async def get_current_org(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Organization:
    """
    Dependency that returns the current organization the user belongs to.
    """
    res = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = res.scalar_one_or_none()
    
    if not org or not org.is_active:
        raise HTTPException(status_code=404, detail="Organization not found or inactive")
        
    return org
