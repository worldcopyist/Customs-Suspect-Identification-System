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
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_secret_key: str = "development-only-change-me"
    # Kept independent from APP_SECRET_KEY, which protects existing encrypted
    # provider credentials and must not be rotated as part of JWT migration.
    jwt_signing_key: str = "development-only-jwt-change-me"
    jwt_issuer: str = "customs-suspect-identification"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'database' / 'customs_training.db'}"
    database_auto_initialize: bool = False
    media_root: Path = PROJECT_ROOT / "results"
    logs_root: Path = BACKEND_ROOT / "logs"
    models_root: Path = BACKEND_ROOT / "models"
    yolo_model_filename: str = "suspect-yolo11n-best.pt"
    # This is the digest of the supplied, approved training artifact.  It is
    # deliberately not accepted from a request or an admin-facing endpoint.
    yolo_model_sha256: str = "d8387eb6ed98d6ff13013f8dc5b1eaac87cb243dc9aa8bc931adf2789abe9329"
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
