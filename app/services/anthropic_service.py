from anthropic import AsyncAnthropic
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class AnthropicService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = AsyncAnthropic(api_key=api_key)

    async def validate_key(self) -> bool:
        """
        Validates the API key.
        - Path A: If it starts with the mock prefix, return True immediately.
        - Path B: Otherwise, call Anthropic API to verify.
        """
        if self.api_key.startswith(settings.ANTHROPIC_API_KEY_MOCK_PREFIX):
            logger.info("Using mock validation for Anthropic API key")
            return True

        try:
            # We call a lightweight endpoint to verify the key
            # In Anthropic's case, we can try to retrieve the models list
            await self.client.models.list(limit=1)
            logger.info("Anthropic API key validated successfully via official SDK")
            return True
        except Exception as e:
            logger.error(f"Failed to validate Anthropic API key: {str(e)}")
            return False

async def validate_anthropic_key(api_key: str) -> bool:
    service = AnthropicService(api_key)
    return await service.validate_key()
