from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """仅保存基础设施配置；密钥不得写入代码或接口响应。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_secret_key: str = "development-only-change-me"
    database_url: str = f"sqlite:///{BACKEND_ROOT / 'data' / 'customs_training.db'}"
    media_root: Path = BACKEND_ROOT / "media"
    logs_root: Path = BACKEND_ROOT / "logs"
    models_root: Path = BACKEND_ROOT / "models"
    yolo_model_filename: str = "suspect-yolo11n-best.pt"
    # This is the digest of the supplied, approved training artifact.  It is
    # deliberately not accepted from a request or an admin-facing endpoint.
    yolo_model_sha256: str = "6f4a8baed78f970a5141cc43e356af8f68c8cef6e7e73ab376ea6893ed4a2b1a"
    yolo_confidence: float = 0.25
    yolo_iou: float = 0.45
    yolo_imgsz: int = 320
    yolo_max_det: int = 100
    yolo_device: str = "cpu"
    inference_timeout_seconds: int = 30
    inference_queue_limit: int = 8
    camera_session_limit: int = 2
    camera_frame_cache_seconds: int = 30
    frontend_root: Path = PROJECT_ROOT
    trusted_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    # Full sessions survive browser restarts and renew on normal use.  Password
    # changes, explicit logout, account disablement and admin revocation still
    # invalidate them immediately.
    session_absolute_seconds: int = 8 * 60 * 60
    session_idle_seconds: int = 30 * 60
    avatar_asset: Path | None = None
    restricted_session_seconds: int = 10 * 60

    @property
    def origin_set(self) -> set[str]:
        return {origin.strip() for origin in self.trusted_origins.split(",") if origin.strip()}

    @property
    def cookie_secure(self) -> bool:
        """本地回环开发不设 Secure，其他环境强制 HTTPS Cookie。"""
        return self.app_env.lower() not in {"development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
