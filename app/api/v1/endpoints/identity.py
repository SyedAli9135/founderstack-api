from fastapi import APIRouter, Depends
from app.core.auth import get_current_user, get_current_org
from app.models import User, Organization
from pydantic import BaseModel
from typing import Optional
import uuid

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

@router.get("/me", response_model=MeResponse)
async def get_me(
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org)
):
    """
    Returns the current authenticated user's profile and their organization details.
    Used by the frontend to initialize state.
    """
    return {
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
