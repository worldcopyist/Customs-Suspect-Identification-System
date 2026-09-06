from fastapi.testclient import TestClient

from app.db.sqlite_driver import ensure_sqlite_runtime
from app.main import create_app


def test_health_endpoint() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_uses_standard_envelope() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/system/status")
    assert response.status_code == 401
    assert "request_id" in response.json()


def test_sqlite_runtime_meets_baseline(tmp_path) -> None:
    runtime = ensure_sqlite_runtime()
    assert runtime.version >= (3, 51, 3)

    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'runtime-check.db'}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA journal_mode = WAL").scalar_one().lower() == "wal"
    engine.dispose()
