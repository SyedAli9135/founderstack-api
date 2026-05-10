from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.api.v1.health import router as health_router
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up FounderStack API...")
    # System dependencies like DB pooling are automatically managed natively 
    # via the SQLAlchemy AsyncEngine instance in core/database.py on startup.
    yield
    logger.info("Shutting down FounderStack API...")

app = FastAPI(
    title="FounderStack AI Backend",
    version="1.0.0",
    description="Headless COO API orchestrated by LangGraph",
    lifespan=lifespan,
)

# Dynamically restrict CORS in production
origins = ["*"] if settings.APP_ENV != "production" else [settings.APP_BASE_URL, "https://founderstack.ai"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
