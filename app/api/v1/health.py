from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from redis.asyncio import Redis
from pinecone import Pinecone
import asyncio

from app.core.database import get_db
from app.config import settings

router = APIRouter()

@router.get("/health", tags=["Health"])
async def health_check(db: AsyncSession = Depends(get_db)):
    checks = {
        "database": "unhealthy",
        "redis": "unhealthy",
        "pinecone": "unhealthy"
    }
    
    # 1. Test Database Connection
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)}"
        
    # 2. Test Redis Connection
    try:
        redis_url = settings.UPSTASH_REDIS_URL or "redis://localhost:6379"
        redis_client = Redis.from_url(redis_url, socket_timeout=2)
        await redis_client.ping()
        await redis_client.aclose()
        checks["redis"] = "healthy"
    except Exception as e:
        checks["redis"] = f"unhealthy: {str(e)}"

    # 3. Test Pinecone Connection
    try:
        if not settings.PINECONE_API_KEY:
            checks["pinecone"] = "skipped (no API key in .env)"
        else:
            loop = asyncio.get_event_loop()
            def test_pinecone():
                pc = Pinecone(api_key=settings.PINECONE_API_KEY)
                pc.list_indexes()
            await loop.run_in_executor(None, test_pinecone)
            checks["pinecone"] = "healthy"
    except Exception as e:
        checks["pinecone"] = f"unhealthy: {str(e)}"
    
    # Determine overall status
    is_critical_healthy = checks["database"] == "healthy" and checks["redis"] == "healthy"
    status_code = 200 if is_critical_healthy else 503
    status_text = "healthy" if status_code == 200 else "degraded"

    return JSONResponse(
        status_code=status_code,
        content={"status": status_text, "checks": checks}
    )
