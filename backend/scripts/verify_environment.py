"""验证后端开发环境关键基线，而不创建业务表或业务数据。"""

from pathlib import Path
from tempfile import TemporaryDirectory

from app.db.sqlite_driver import ensure_sqlite_runtime


def main() -> None:
    runtime = ensure_sqlite_runtime()
    from sqlalchemy import create_engine

    with TemporaryDirectory(prefix="customs-sqlite-check-") as directory:
        database = Path(directory) / "check.db"
        engine = create_engine(f"sqlite:///{database}")
        with engine.connect() as connection:
            version = connection.exec_driver_sql("SELECT sqlite_version()").scalar_one()
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode = WAL").scalar_one()
        engine.dispose()

    assert tuple(map(int, version.split("."))) >= (3, 51, 3)
    assert foreign_keys == 1
    assert journal_mode.lower() == "wal"
    print(f"SQLite {runtime.version_text}; foreign_keys=ON; journal_mode=WAL")


if __name__ == "__main__":
    main()
