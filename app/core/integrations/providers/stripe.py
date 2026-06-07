import httpx

async def validate_token(api_key: str) -> bool:
    """Validate Stripe API key."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.stripe.com/v1/account",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        return response.status_code == 200
