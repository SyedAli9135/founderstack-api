import time
import uuid
from functools import partial
from typing import Any, Protocol, runtime_checkable

from cryptography.fernet import InvalidToken
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.security import decrypt_secret
from app.models.identity import User
from app.models.integration import ApiKeyRegistry
import litellm


@runtime_checkable
class LLMCallable(Protocol):
    """
    A fully-configured LiteLLM callable. Both api_key and model are pre-bound.
    Callers only supply messages and optional litellm kwargs.

    Example:
        response = await llm(messages=[{"role": "user", "content": "Hello"}])
        response = await llm(messages=[...], max_tokens=1024, temperature=0.2)
    """
    async def __call__(self, *, messages: list, **kwargs) -> Any: ...


# In-process TTL cache: org_id -> (plaintext_key, expires_at monotonic timestamp)
# Stores plaintext in memory only — never written to disk, Redis, or logs.
_key_cache: dict[uuid.UUID, tuple[str, float]] = {}
_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes


def _get_cached_key(org_id: uuid.UUID) -> str | None:
    entry = _key_cache.get(org_id)
    if entry is None:
        return None
    plaintext_key, expires_at = entry
    if time.monotonic() > expires_at:
        del _key_cache[org_id]
        return None
    return plaintext_key


def _set_cached_key(org_id: uuid.UUID, plaintext_key: str) -> None:
    _key_cache[org_id] = (plaintext_key, time.monotonic() + _CACHE_TTL_SECONDS)


def invalidate_llm_cache(org_id: uuid.UUID) -> None:
    """Call whenever the org's API key is rotated or deleted."""
    _key_cache.pop(org_id, None)


async def resolve_llm_client(
    org_id: uuid.UUID,
    db: AsyncSession,
    model: str,
) -> LLMCallable:
    """
    Fetches, decrypts, and wraps the org's Anthropic key into a fully-bound LiteLLM callable.

    Both the api_key and model are pre-bound — callers only pass messages and optional kwargs.
    The model must be a valid LiteLLM model string, e.g. "anthropic/claude-sonnet-4-6".

    Cache-first: skips the DB round-trip for 5 minutes after the first successful fetch.
    The key is invalidated immediately if the org rotates or deletes it via invalidate_llm_cache().

    Use this inside LangGraph nodes where you have org_id, db, and model from state.

    Raises:
        HTTPException 400 — no valid key found for the org.
        HTTPException 500 — stored key fails decryption (corrupted or wrong ENCRYPTION_KEY).
    """
    plaintext_key = _get_cached_key(org_id)

    if plaintext_key is None:
        stmt = select(ApiKeyRegistry).where(
            ApiKeyRegistry.org_id == org_id,
            ApiKeyRegistry.provider == "anthropic",
            ApiKeyRegistry.is_valid == True,
        )
        result = await db.execute(stmt)
        key_record = result.scalar_one_or_none()

        if key_record is None:
            raise HTTPException(
                status_code=400,
                detail="No valid Anthropic API key configured. Add your key in Settings.",
            )

        try:
            plaintext_key = decrypt_secret(key_record.encrypted_key)
        except InvalidToken:
            raise HTTPException(
                status_code=500,
                detail="API key decryption failed. Please re-save your key in Settings.",
            )

        _set_cached_key(org_id, plaintext_key)

    return partial(litellm.acompletion, api_key=plaintext_key, model=model)


class GetLLMClient:
    """
    FastAPI dependency factory for routes where the model is known at route definition time.

    Usage:
        @router.post("/validate")
        async def validate(
            llm: LLMCallable = Depends(GetLLMClient("anthropic/claude-haiku-4-5-20251001")),
        ):
            response = await llm(messages=[{"role": "user", "content": "ping"}])

    For routes where the model comes from the request body (e.g. Workflow 9 run),
    call resolve_llm_client() directly inside the handler instead.
    """

    def __init__(self, model: str) -> None:
        self.model = model

    async def __call__(
        self,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> LLMCallable:
        return await resolve_llm_client(current_user.org_id, db, self.model)
