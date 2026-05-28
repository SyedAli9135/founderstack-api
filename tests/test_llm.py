import time
import uuid
import pytest
from functools import partial
from sqlalchemy import insert, select, delete
from fastapi import HTTPException

from app.core.llm import (
    GetLLMClient,
    _key_cache,
    invalidate_llm_cache,
    resolve_llm_client,
)
from app.core.security import encrypt_secret
from app.models.identity import User
from app.models.integration import ApiKeyRegistry

MODEL = "anthropic/claude-sonnet-4-6"


@pytest.fixture(autouse=True)
def clear_llm_cache():
    """Wipe the in-process LLM key cache before and after every test."""
    _key_cache.clear()
    yield
    _key_cache.clear()


# ── Happy path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_llm_client_returns_callable(db_session, setup_user_org):
    """Test that resolve_llm_client returns a callable with api_key and model pre-bound."""
    # 1. Setup: insert a valid encrypted key for the org
    org_id = setup_user_org["org_id"]
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key=encrypt_secret("sk-ant-real-key-123"),
            kms_key_id="local-fernet",
            is_valid=True,
        )
    )
    await db_session.commit()

    # 2. Execute
    result = await resolve_llm_client(org_id, db_session, MODEL)

    # 3. Verify: must be a partial with both api_key and model bound
    assert callable(result)
    assert isinstance(result, partial)
    assert result.keywords["api_key"] == "sk-ant-real-key-123"
    assert result.keywords["model"] == MODEL


@pytest.mark.asyncio
async def test_model_is_bound_from_request_param(db_session, setup_user_org):
    """Test that the model provided by the caller is the one bound in the returned callable."""
    # 1. Setup
    org_id = setup_user_org["org_id"]
    haiku = "anthropic/claude-haiku-4-5-20251001"
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key=encrypt_secret("sk-ant-model-test"),
            kms_key_id="local-fernet",
            is_valid=True,
        )
    )
    await db_session.commit()

    # 2. Execute with haiku model
    result = await resolve_llm_client(org_id, db_session, haiku)

    # 3. Verify model is haiku, not the default sonnet
    assert result.keywords["model"] == haiku


@pytest.mark.asyncio
async def test_different_models_same_org_share_cached_key(db_session, setup_user_org):
    """Test that calling with two different models yields the same api_key but different model bindings."""
    # 1. Setup
    org_id = setup_user_org["org_id"]
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key=encrypt_secret("sk-ant-shared-key"),
            kms_key_id="local-fernet",
            is_valid=True,
        )
    )
    await db_session.commit()

    # 2. Execute with two models
    r1 = await resolve_llm_client(org_id, db_session, "anthropic/claude-sonnet-4-6")
    r2 = await resolve_llm_client(org_id, db_session, "anthropic/claude-haiku-4-5-20251001")

    # 3. Verify: same key, different model
    assert r1.keywords["api_key"] == r2.keywords["api_key"] == "sk-ant-shared-key"
    assert r1.keywords["model"] != r2.keywords["model"]


# ── Error paths ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_llm_client_raises_400_when_no_key(db_session, setup_user_org):
    """Test that resolve_llm_client raises HTTP 400 when no valid key exists for the org."""
    # 1. Setup: no key inserted — DB returns nothing
    org_id = setup_user_org["org_id"]

    # 2. Execute & Verify
    with pytest.raises(HTTPException) as exc_info:
        await resolve_llm_client(org_id, db_session, MODEL)

    assert exc_info.value.status_code == 400
    assert "Add your key in Settings" in exc_info.value.detail


@pytest.mark.asyncio
async def test_resolve_llm_client_raises_400_for_deactivated_key(db_session, setup_user_org):
    """Test that a key with is_valid=False is treated as absent — raises HTTP 400."""
    # 1. Setup: insert a key but mark it invalid
    org_id = setup_user_org["org_id"]
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key=encrypt_secret("sk-ant-deactivated"),
            kms_key_id="local-fernet",
            is_valid=False,
        )
    )
    await db_session.commit()

    # 2. Execute & Verify
    with pytest.raises(HTTPException) as exc_info:
        await resolve_llm_client(org_id, db_session, MODEL)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_resolve_llm_client_raises_500_for_corrupted_key(db_session, setup_user_org):
    """Test that a record with a corrupted encrypted_key raises HTTP 500."""
    # 1. Setup: insert a record with non-Fernet data
    org_id = setup_user_org["org_id"]
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key="this-is-not-valid-fernet-data",
            kms_key_id="local-fernet",
            is_valid=True,
        )
    )
    await db_session.commit()

    # 2. Execute & Verify
    with pytest.raises(HTTPException) as exc_info:
        await resolve_llm_client(org_id, db_session, MODEL)

    assert exc_info.value.status_code == 500
    assert "decryption failed" in exc_info.value.detail


# ── Cache behaviour ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_call_populates_cache(db_session, setup_user_org):
    """Test that a successful resolve populates the in-process cache."""
    # 1. Setup
    org_id = setup_user_org["org_id"]
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key=encrypt_secret("sk-ant-cache-populate"),
            kms_key_id="local-fernet",
            is_valid=True,
        )
    )
    await db_session.commit()

    assert org_id not in _key_cache

    # 2. Execute
    await resolve_llm_client(org_id, db_session, MODEL)

    # 3. Verify cache is now populated with the plaintext key
    assert org_id in _key_cache
    cached_key, _ = _key_cache[org_id]
    assert cached_key == "sk-ant-cache-populate"


@pytest.mark.asyncio
async def test_second_call_served_from_cache_not_db(db_session, setup_user_org):
    """Test that a cached entry is used on the second call even if the DB row is deleted."""
    # 1. Setup: insert key, call once to populate cache
    org_id = setup_user_org["org_id"]
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key=encrypt_secret("sk-ant-cached"),
            kms_key_id="local-fernet",
            is_valid=True,
        )
    )
    await db_session.commit()
    await resolve_llm_client(org_id, db_session, MODEL)

    # 2. Delete the DB row — second call must still succeed via cache
    await db_session.execute(
        delete(ApiKeyRegistry).where(ApiKeyRegistry.org_id == org_id)
    )
    await db_session.commit()

    # 3. Execute & Verify: resolves from cache, not the (now-empty) DB
    result = await resolve_llm_client(org_id, db_session, MODEL)
    assert result.keywords["api_key"] == "sk-ant-cached"


@pytest.mark.asyncio
async def test_stale_cache_entry_bypassed_after_ttl(db_session, setup_user_org):
    """Test that an expired cache entry is ignored and the DB is re-queried."""
    # 1. Setup: insert key in DB; manually plant a stale cache entry (already expired)
    org_id = setup_user_org["org_id"]
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key=encrypt_secret("sk-ant-fresh"),
            kms_key_id="local-fernet",
            is_valid=True,
        )
    )
    await db_session.commit()
    _key_cache[org_id] = ("sk-ant-stale", time.monotonic() - 1.0)

    # 2. Execute — expired entry must be discarded, DB re-queried
    result = await resolve_llm_client(org_id, db_session, MODEL)

    # 3. Verify fresh key was fetched, not the stale one
    assert result.keywords["api_key"] == "sk-ant-fresh"


@pytest.mark.asyncio
async def test_invalidate_clears_cache_forces_db_refetch(db_session, setup_user_org):
    """Test that invalidate_llm_cache removes the entry and the next call re-queries the DB."""
    # 1. Setup: populate cache
    org_id = setup_user_org["org_id"]
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key=encrypt_secret("sk-ant-original"),
            kms_key_id="local-fernet",
            is_valid=True,
        )
    )
    await db_session.commit()
    await resolve_llm_client(org_id, db_session, MODEL)
    assert org_id in _key_cache

    # 2. Invalidate
    invalidate_llm_cache(org_id)
    assert org_id not in _key_cache

    # 3. Next call hits DB and succeeds
    result = await resolve_llm_client(org_id, db_session, MODEL)
    assert result.keywords["api_key"] == "sk-ant-original"


@pytest.mark.asyncio
async def test_invalidate_is_safe_when_org_not_cached():
    """Test that invalidate_llm_cache does not raise when the org has no cache entry."""
    invalidate_llm_cache(uuid.uuid4())


# ── GetLLMClient dependency factory ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_llm_client_dependency_resolves_for_authenticated_user(db_session, setup_user_org):
    """Test that GetLLMClient dependency factory resolves the client for the current user's org."""
    # 1. Setup: insert key and fetch the real User object from DB
    org_id = setup_user_org["org_id"]
    await db_session.execute(
        insert(ApiKeyRegistry).values(
            org_id=org_id,
            provider="anthropic",
            key_prefix="sk-ant-...",
            encrypted_key=encrypt_secret("sk-ant-dep-key"),
            kms_key_id="local-fernet",
            is_valid=True,
        )
    )
    await db_session.commit()

    res = await db_session.execute(select(User).where(User.id == setup_user_org["user_id"]))
    current_user = res.scalar_one()

    # 2. Execute
    dep = GetLLMClient(MODEL)
    result = await dep(current_user=current_user, db=db_session)

    # 3. Verify
    assert isinstance(result, partial)
    assert result.keywords["model"] == MODEL
    assert result.keywords["api_key"] == "sk-ant-dep-key"
