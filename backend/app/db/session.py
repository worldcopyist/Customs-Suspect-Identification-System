"""SQLite 连接、事务和会话工厂。"""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _make_engine() -> Engine:
    settings = get_settings()
    database_path = settings.database_url.removeprefix("sqlite:///")
    if database_path and database_path != ":memory:":
        path = Path(database_path)
        # 相对路径按 backend 工作目录解释，绝对路径保持其部署者指定的位置。
        if not path.is_absolute():
            path = settings.frontend_root / "backend" / path
        path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):  # type: ignore[no-untyped-def]
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = FULL")
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
