from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    data: T
    request_id: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str


class ServiceComponent(BaseModel):
    state: str = Field(description="READY、UNAVAILABLE 或 DEGRADED")


class SystemStatus(BaseModel):
    database: ServiceComponent
    model: ServiceComponent
    llm: ServiceComponent
    avatar: ServiceComponent
