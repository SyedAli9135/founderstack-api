from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update, select
from pydantic import BaseModel
from typing import Optional, Any
from app.api.v1.schemas.base import SuccessEnvelope
import logging

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.identity import User, Organization
from app.models.integration import ApiKeyRegistry
from app.services.anthropic_service import validate_anthropic_key
from app.core.security import encrypt_secret
from app.core.llm import invalidate_llm_cache
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)


class ApiKeySubmit(BaseModel):
    api_key: str


class ApiKeyStatusDetails(BaseModel):
    provider: str
    is_valid: bool
    key_prefix: str


@router.post("/api-key", status_code=status.HTTP_201_CREATED)
async def submit_api_key(
    payload: ApiKeySubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Submits, validates and encrypts an Anthropic API key.
    - Validates key (mock or real).
    - Encrypts key via Fernet.
    - Stores in ApiKeyRegistry.
    - Updates Organization state.
    """
    # 1. Validate the key (Dual-path: Mock vs Real SDK)
    try:
        is_valid = await validate_anthropic_key(payload.api_key)
    except Exception as e:
        logger.error(f"Error during key validation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The validation service encountered an error. Please try again later."
        )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The provided Anthropic API key is invalid or inactive. Please ensure it starts with 'sk-ant-' and has active usage permissions."
        )

    # 2. Encrypt the key
    encrypted_key = encrypt_secret(payload.api_key)
    key_prefix = payload.api_key[:7] + "..."

    # 3. UPSERT into ApiKeyRegistry
    # Note: We enforce one Anthropic key per org for simplicity in V1
    existing_key_stmt = select(ApiKeyRegistry).where(
        ApiKeyRegistry.org_id == current_user.org_id,
        ApiKeyRegistry.provider == "anthropic"
    )
    result = await db.execute(existing_key_stmt)
    existing_key = result.scalar_one_or_none()

    if existing_key:
        existing_key.encrypted_key = encrypted_key
        existing_key.key_prefix = key_prefix
        existing_key.is_valid = True
        key_id = existing_key.id
    else:
        new_key = ApiKeyRegistry(
            id=uuid.uuid4(),
            org_id=current_user.org_id,
            provider="anthropic",
            key_prefix=key_prefix,
            encrypted_key=encrypted_key,
            kms_key_id="local-fernet",
            is_valid=True
        )
        db.add(new_key)
        key_id = new_key.id

    # 4. Update Organization
    org_update_stmt = (
        update(Organization)
        .where(Organization.id == current_user.org_id)
        .values(
            active_api_key_id=key_id,
            onboarding_completed=True
        )
    )
    await db.execute(org_update_stmt)

    await db.commit()
    invalidate_llm_cache(current_user.org_id)

    return SuccessEnvelope(
        message="Anthropic API key has been securely encrypted and validated. Your workspace is now active.",
        data={
            "provider": "anthropic",
            "key_prefix": key_prefix
        }
    )


@router.get("/api-key/status", response_model=SuccessEnvelope[Optional[ApiKeyStatusDetails]])
async def get_api_key_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns the status of the organization's Anthropic API key."""
    stmt = select(ApiKeyRegistry).where(
        ApiKeyRegistry.org_id == current_user.org_id,
        ApiKeyRegistry.provider == "anthropic"
    )
    result = await db.execute(stmt)
    key = result.scalar_one_or_none()

    if not key:
        return SuccessEnvelope(data=None)

    data = ApiKeyStatusDetails(
        provider=key.provider,
        is_valid=key.is_valid,
        key_prefix=key.key_prefix
    )
    return SuccessEnvelope(data=data)

@router.delete("/api-key", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Deactivates the organization's Anthropic API key.
    """
    # 1. Update Key Registry
    await db.execute(
        update(ApiKeyRegistry)
        .where(ApiKeyRegistry.org_id == current_user.org_id)
        .where(ApiKeyRegistry.provider == "anthropic")
        .values(is_valid=False)
    )

    # 2. Update Organization
    await db.execute(
        update(Organization)
        .where(Organization.id == current_user.org_id)
        .values(active_api_key_id=None)
    )

    # 3. Invalidate cache
    invalidate_llm_cache(current_user.org_id)

    await db.commit()
    return None
