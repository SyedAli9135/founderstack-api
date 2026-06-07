from redis.asyncio import Redis
from app.config import settings

def get_redis_client() -> Redis:
    redis_url = settings.UPSTASH_REDIS_URL or "redis://localhost:6379"
    # Note: UPSTASH_REDIS_TOKEN is handled if the URL already contains it or 
    # if using a specific Upstash Redis client, but for standard redis-py 
    # the URL is usually enough for both local and Upstash.
    return Redis.from_url(redis_url, decode_responses=True)

# For long-lived global client if needed
# redis_client = get_redis_client()
