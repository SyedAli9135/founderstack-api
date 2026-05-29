import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds a unique Request-ID to every request.
    This ID is returned in the response headers and can be used for 
    distributed tracing and log correlation.
    """
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        
        # Add request_id to the request state so it can be accessed by handlers/exceptions
        request.state.request_id = request_id
        
        response: Response = await call_next(request)
        
        # Add request_id to the response headers
        response.headers["X-Request-ID"] = request_id
        return response
