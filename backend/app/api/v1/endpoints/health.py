from fastapi import APIRouter, Request

from app.core.errors import request_id
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import ProviderConfig
from app.schemas.common import ServiceComponent, SuccessResponse, SystemStatus
from app.services.llm import validation_fingerprint

router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=SuccessResponse[SystemStatus])
async def system_status(request: Request) -> SuccessResponse[SystemStatus]:
    """框架健康状态；不暴露路径、依赖版本、密钥或模型细节。"""
    with SessionLocal() as db:
        configs = list(db.scalars(select(ProviderConfig).where(ProviderConfig.enabled.is_(True))))
        llm_state = "READY" if any(item.validation_fingerprint == validation_fingerprint(item) for item in configs) else "UNAVAILABLE"
    return SuccessResponse(
        data=SystemStatus(
            database=ServiceComponent(state="UNAVAILABLE"),
            model=ServiceComponent(state="READY" if request.app.state.inference_coordinator.available else "UNAVAILABLE"),
            llm=ServiceComponent(state=llm_state),
            avatar=ServiceComponent(state="UNAVAILABLE"),
        ),
        request_id=request_id(request),
    )
