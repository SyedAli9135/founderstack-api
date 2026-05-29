import logging
import traceback
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.config import settings
from app.api.v1.schemas.base import ErrorEnvelope, ErrorDetail

logger = logging.getLogger(__name__)

async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all handler for unexpected errors. 
    Masks internal details in production and provides a request_id for tracing.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    # Log the full traceback for developers
    logger.error(f"Unhandled Exception [ReqID: {request_id}]: {str(exc)}\n{traceback.format_exc()}")
    
    message = "An unexpected internal server error occurred. Please contact support with the Request ID."
    
    # In development, we can be more helpful
    if settings.APP_ENV == "development":
        message = str(exc)

    error_response = ErrorEnvelope(
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message=message,
            request_id=request_id
        )
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump()
    )

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Standardizes the format of manual HTTPExceptions.
    Handles 500s raised via HTTPException as INTERNAL_SERVER_ERROR.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    code = "HTTP_EXCEPTION"
    if exc.status_code >= 500:
        code = "INTERNAL_SERVER_ERROR"

    error_response = ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=exc.detail,
            request_id=request_id
        )
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump()
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Standardizes the format of Pydantic validation errors.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    error_response = ErrorEnvelope(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="Input validation failed",
            request_id=request_id,
            detail=exc.errors()
        )
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response.model_dump()
    )
