from collections.abc import AsyncIterator
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Role, User, AssistantRequest, Detection, CameraSession
from app.models.extension import OperationLog
from app.services.security import now
from app.schemas.auth import DEFAULT_PERMISSIONS
from app.services.security import password_hash
from app.services.detection import InferenceCoordinator
import threading


def initialize_database() -> None:
    """执行版本化迁移后，只在空库中初始化受保护的 admin 账户。"""
    settings = get_settings()
    alembic_config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    alembic_config.set_main_option("script_location",str(Path(__file__).resolve().parents[2]/"migrations"))
    alembic_config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_config, "head")
    with SessionLocal.begin() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        if admin is None:
            db.add(User(
                username="admin", display_name="系统超级管理员", password_hash=password_hash("admin123"),
                role=Role.SUPER_ADMIN.value, is_builtin=True, must_change_password=True,
                permissions=sorted(DEFAULT_PERMISSIONS),
            ))
        elif admin.role != Role.SUPER_ADMIN.value or not admin.is_builtin:
            raise RuntimeError("初始化冲突：已有同名 admin 账户，但其并非内置超级管理员")
        for row in db.scalars(select(AssistantRequest).where(AssistantRequest.state.in_(["PREPARED","QUEUED","RUNNING"]))):
            if row.state=="RUNNING":row.state="FAILED";row.billing_state="UNKNOWN";row.error_code="OUTCOME_UNKNOWN"
            else:row.state="EXPIRED" if row.state=="PREPARED" else "CANCELLED";row.error_code="PROCESS_RESTARTED"
            row.finished_at=now()
        for row in db.scalars(select(Detection).where(Detection.state.in_(["RUNNING","QUEUED"]))):
            if row.state=="QUEUED":row.state="PENDING"
            else:row.state="FAILED";row.error_code="PROCESS_RESTARTED";row.finished_at=now()
        for row in db.scalars(select(CameraSession).where(CameraSession.state.in_(["ACTIVE","PAUSED"]))):row.state="FAILED";row.generation+=1
        db.add(OperationLog(level="INFO",module="system",event_code="SERVICE_STARTED",safe_context={}))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """为后续 DB、推理调度器和 HTTP 客户端保留唯一的启动/停止入口。"""
    settings = get_settings()
    settings.media_root.mkdir(parents=True, exist_ok=True)
    settings.models_root.mkdir(parents=True, exist_ok=True)
    initialize_database()
    app.state.inference_coordinator = InferenceCoordinator(settings)
    app.state.camera_cache = {}
    app.state.camera_cache_lock = threading.Lock()
    app.state.camera_last_seq = {}
    app.state.camera_last_saved = {}
    app.state.camera_in_flight = set()
    # The semaphore enforces the documented global cloud-text concurrency
    # limit without sharing an HTTP client or credentials with inference.
    app.state.llm_semaphore = asyncio.Semaphore(2)
    try:
        yield
    finally:
        app.state.inference_coordinator.close()
        with SessionLocal.begin() as db:
            db.add(OperationLog(level="INFO",module="system",event_code="SERVICE_STOPPED",safe_context={}))
