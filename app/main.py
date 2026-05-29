from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.health import router as health_router
from app.api.webhooks.clerk import router as clerk_webhook_router
from app.api.v1.endpoints.identity import router as identity_router
from app.api.v1.endpoints.settings import router as settings_router
from app.api.middleware import RequestIDMiddleware
from app.core.exceptions import (
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler
)
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

# --- GLOBAL SAFETY NET & HARDENING ---

# 1. Request ID Tracking Middleware
app.add_middleware(RequestIDMiddleware)

# 2. Global Exception Handlers
# Standardize validation errors
app.add_exception_handler(RequestValidationError, validation_exception_handler)
# Standardize manual HTTPExceptions
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
# Catch-all for unexpected errors (The Master Catcher)
app.add_exception_handler(Exception, global_exception_handler)

# -------------------------------------

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
app.include_router(clerk_webhook_router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(identity_router, prefix="/api/v1/auth", tags=["Identity"])
app.include_router(settings_router, prefix="/api/v1/settings", tags=["Settings"])
