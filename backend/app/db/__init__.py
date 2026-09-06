"""SQLite、SQLAlchemy 会话和 Alembic 集成入口。"""

from app.db.sqlite_driver import ensure_sqlite_runtime

ensure_sqlite_runtime()
