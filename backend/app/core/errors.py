from uuid import uuid4
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT, HTTP_500_INTERNAL_SERVER_ERROR

from app.schemas.common import ErrorBody, ErrorResponse
from app.services.security import ApiError

logger = logging.getLogger("customs_training")


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("validation_error request_id=%s method=%s route=%s errors=%s", request_id(request), request.method, getattr(request.scope.get('route'),'path','unmatched'), len(exc.errors()))
    body = ErrorResponse(
        error=ErrorBody(code="VALIDATION_ERROR", message="请求参数不符合接口约束", details={"errors": [{"loc":e["loc"],"type":e["type"]} for e in exc.errors()]}),
        request_id=request_id(request),
    )
    return JSONResponse(status_code=HTTP_422_UNPROCESSABLE_CONTENT, content=body.model_dump(mode="json"))


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    logger.warning("api_error request_id=%s method=%s route=%s code=%s", request_id(request), request.method, getattr(request.scope.get('route'),'path','unmatched'), exc.code)
    body = ErrorResponse(
        error=ErrorBody(code=exc.code, message=exc.message, details=exc.details), request_id=request_id(request)
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_error request_id=%s exception_type=%s",request_id(request),type(exc).__name__)
    try:
        from app.db.session import SessionLocal
        from app.models.extension import OperationLog
        with SessionLocal.begin() as db:
            db.add(OperationLog(level='ERROR',module='api',event_code='UNHANDLED_ERROR',request_id=request_id(request),safe_context={'exception_type':type(exc).__name__,'route':getattr(request.scope.get('route'),'path','unknown')}))
    except Exception:logger.error('operation_log_persist_failed request_id=%s',request_id(request))
    body = ErrorResponse(
        error=ErrorBody(code="INTERNAL_ERROR", message="服务内部异常"),
        request_id=request_id(request),
    )
    return JSONResponse(status_code=HTTP_500_INTERNAL_SERVER_ERROR, content=body.model_dump(mode="json"),headers={'X-Request-ID':request_id(request),'Cache-Control':'no-store'})
