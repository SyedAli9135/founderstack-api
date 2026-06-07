import hmac
import hashlib
import json
import secrets
from typing import Tuple, Optional, Dict
from fastapi import HTTPException
from app.config import settings
from app.core.redis import get_redis_client

STATE_TTL = 600  # 10 minutes

def _get_signature(nonce: str) -> str:
    """Generate HMAC-SHA256 signature for a nonce."""
    secret = settings.OAUTH_STATE_SECRET.get_secret_value().encode()
    return hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest()

async def generate_state(org_id: str, service: str, extra_data: Optional[Dict] = None) -> str:
    """
    Generate a secure OAuth state token.
    1. Generate random nonce.
    2. Store metadata in Redis with 10 min TTL.
    3. Sign nonce with HMAC-SHA256.
    4. Return state = f"{nonce}.{hmac_sig}"
    """
    nonce = secrets.token_urlsafe(32)
    redis = get_redis_client()
    
    # Store in Redis
    payload = {"org_id": org_id, "service": service}
    if extra_data:
        payload["extra_data"] = extra_data
    
    state_data = json.dumps(payload)
    await redis.setex(f"oauth_state:{nonce}", STATE_TTL, state_data)
    await redis.aclose()
    
    # Sign
    sig = _get_signature(nonce)
    return f"{nonce}.{sig}"

async def verify_state(state: str) -> Tuple[str, str, Optional[Dict]]:
    """
    Verify an OAuth state token and recover org_id/service/extra_data.
    1. Split state into nonce, sig.
    2. Recompute HMAC and compare.
    3. Look up nonce in Redis.
    4. Delete key immediately (one-time use).
    5. Return (org_id, service, extra_data).
    """
    try:
        nonce, sig = state.split(".")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state format")

    # Verify signature
    expected_sig = _get_signature(nonce)
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=400, detail="Invalid state signature")

    redis = get_redis_client()
    key = f"oauth_state:{nonce}"
    
    # Get from Redis
    state_data_raw = await redis.get(key)
    if not state_data_raw:
        await redis.aclose()
        raise HTTPException(status_code=400, detail="State expired or already used")

    # Delete immediately (one-time use)
    await redis.delete(key)
    await redis.aclose()

    # Parse and return
    try:
        data = json.loads(state_data_raw)
        return data["org_id"], data["service"], data.get("extra_data")
    except (json.JSONDecodeError, KeyError):
        raise HTTPException(status_code=400, detail="Malformed state data")
