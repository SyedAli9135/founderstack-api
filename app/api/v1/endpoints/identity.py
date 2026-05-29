from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user, get_current_org
from app.models import User, Organization
from app.config import settings
from pydantic import BaseModel
from typing import Optional, Any
from app.api.v1.schemas.base import SuccessEnvelope
import uuid
import jwt
from datetime import datetime, timedelta, timezone

router = APIRouter()

class UserProfile(BaseModel):
    id: uuid.UUID
    email: str
    full_name: Optional[str]
    role: str
    avatar_url: Optional[str]

class OrgProfile(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan_tier: str

class MeResponse(BaseModel):
    user: UserProfile
    organization: Optional[OrgProfile]

@router.get("/me", response_model=SuccessEnvelope[MeResponse])
async def get_me(
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org)
):
    """
    Returns the current authenticated user's profile and their organization details.
    Used by the frontend to initialize state.
    """
    data = {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "avatar_url": user.avatar_url,
        },
        "organization": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "plan_tier": org.plan_tier,
        }
    }
    return SuccessEnvelope(data=data)

class DevTokenRequest(BaseModel):
    clerk_user_id: str
    extra_claims: Optional[dict] = None

@router.post("/dev-token", tags=["System"])
async def generate_dev_token(payload: DevTokenRequest):
    """
    Utility endpoint to generate a mock JWT for local development/testing.
    STRICTLY DISABLED IN PRODUCTION.
    """
    if settings.APP_ENV == "production":
        raise HTTPException(
            status_code=403, 
            detail="Security Violation: Developer token generation is strictly disabled in production environments."
        )
    
    # Standard claims
    claims = {
        "sub": payload.clerk_user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        "iat": datetime.now(timezone.utc)
    }
    
    # Merge extra claims if provided
    if payload.extra_claims:
        claims.update(payload.extra_claims)
    
    # Generate a JWT that matches our auth.py decode logic (options={"verify_signature": False})
    token = jwt.encode(claims, "dummy_secret", algorithm="HS256")
    
    return SuccessEnvelope(
        message="Development token generated successfully.",
        data={"token": token, "expires_in": "30 minutes"}
    )
