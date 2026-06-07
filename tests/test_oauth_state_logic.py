import pytest
import json
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from app.core.integrations.state import generate_state, verify_state, _get_signature

@pytest.mark.asyncio
async def test_generate_and_verify_state_success():
    """Test that a state can be generated and successfully verified."""
    # 1. Setup: Mock Redis
    mock_redis = AsyncMock()
    with patch("app.core.integrations.state.get_redis_client", return_value=mock_redis):
        org_id = "org_123"
        service = "slack"
        
        # 2. Execution: Generate state
        state = await generate_state(org_id, service)
        
        # 3. Verification: Internal structure
        assert "." in state
        nonce, sig = state.split(".")
        assert sig == _get_signature(nonce)
        
        # Check Redis storage
        mock_redis.setex.assert_called_once()
        args, _ = mock_redis.setex.call_args
        assert args[0] == f"oauth_state:{nonce}"
        stored_payload = json.loads(args[2])
        assert stored_payload["org_id"] == org_id
        assert stored_payload["service"] == service

        # 4. Execution: Verify state
        mock_redis.get.return_value = args[2] # Return what was set
        
        recovered_org, recovered_service, extra_data = await verify_state(state)
        
        # 5. Verification: Recovery and Cleanup
        assert recovered_org == org_id
        assert recovered_service == service
        assert extra_data is None
        mock_redis.delete.assert_called_once_with(f"oauth_state:{nonce}")

@pytest.mark.asyncio
async def test_verify_state_invalid_signature():
    """Test that verification fails if the signature is tampered with."""
    state = "nonce.invalid_sig"
    with pytest.raises(HTTPException) as excinfo:
        await verify_state(state)
    
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid state signature"

@pytest.mark.asyncio
async def test_verify_state_expired_or_missing():
    """Test that verification fails if the state is missing from Redis."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    
    with patch("app.core.integrations.state.get_redis_client", return_value=mock_redis):
        nonce = "valid_nonce"
        sig = _get_signature(nonce)
        state = f"{nonce}.{sig}"
        
        with pytest.raises(HTTPException) as excinfo:
            await verify_state(state)
        
        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == "State expired or already used"

@pytest.mark.asyncio
async def test_generate_state_with_extra_data():
    """Test that extra_data (like PKCE verifier) is correctly stored and recovered."""
    mock_redis = AsyncMock()
    with patch("app.core.integrations.state.get_redis_client", return_value=mock_redis):
        extra = {"code_verifier": "ver_123"}
        state = await generate_state("org_1", "twitter", extra_data=extra)
        
        nonce = state.split(".")[0]
        args, _ = mock_redis.setex.call_args
        stored_payload = json.loads(args[2])
        assert stored_payload["extra_data"] == extra

        # Verification
        mock_redis.get.return_value = args[2]
        _, _, recovered_extra = await verify_state(state)
        assert recovered_extra == extra
