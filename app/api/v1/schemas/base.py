from typing import Generic, Optional, TypeVar, Any
from pydantic import BaseModel

T = TypeVar("T")

class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: Optional[str] = None
    detail: Any = None

class SuccessEnvelope(BaseModel, Generic[T]):
    status: str = "success"
    message: Optional[str] = None
    data: Optional[T] = None

class ErrorEnvelope(BaseModel):
    status: str = "error"
    error: ErrorDetail
