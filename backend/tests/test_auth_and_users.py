from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event

from app.core.config import get_settings
from app.db import session as db_session
from app.main import create_app


ORIGIN = "http://127.0.0.1:8000"


def _configure_test_database(path: Path):
    """将全局会话工厂指向临时库，同时让启动迁移使用该 URL。"""
    old_url = get_settings().database_url
    old_bind = db_session.SessionLocal.kw.get("bind")
    url = f"sqlite:///{path}"
    get_settings().database_url = url
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _):  # type: ignore[no-untyped-def]
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")

    db_session.SessionLocal.configure(bind=engine)
    return old_url, old_bind, engine


def _csrf(client: TestClient) -> str:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


def _write(client: TestClient, method: str, path: str, payload: dict, csrf: str | None = None):
    return client.request(
        method, path, json=payload, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf or _csrf(client)}
    )


def test_authentication_role_boundaries_and_revocation(tmp_path: Path) -> None:
    old_url, old_bind, engine = _configure_test_database(tmp_path / "auth.db")
    try:
        with TestClient(create_app(), base_url=ORIGIN) as super_client, TestClient(create_app(), base_url=ORIGIN) as bob_client:
            # 注册端点拒绝由客户端指定角色，且正常注册固定为 USER。
            response = _write(super_client, "POST", "/api/v1/auth/register", {
                "username": "role_attempt", "display_name": "越权尝试", "password": "RoleAttempt!123", "password_confirm": "RoleAttempt!123", "role": "ADMIN",
            })
            assert response.status_code == 422
            response = _write(super_client, "POST", "/api/v1/auth/register", {
                "username": "bob_01", "display_name": "Bob", "password": "BobSecure!12345", "password_confirm": "BobSecure!12345",
            })
            assert response.status_code == 201
            assert response.json()["data"]["role"] == "USER"
            # V1.2 明确拒绝旧的 8 字符注册策略。
            response = _write(super_client, "POST", "/api/v1/auth/register", {
                "username": "min_08", "display_name": "Minimum", "password": "Eight!12", "password_confirm": "Eight!12",
            })
            assert response.status_code == 422

            # 内置管理员首次登录只能改密；改密后旧会话不可再使用。
            response = _write(super_client, "POST", "/api/v1/auth/login", {"username": "admin", "password": "admin123"})
            restricted_csrf = response.json()["data"]["csrf_token"]
            assert response.json()["data"]["session_phase"] == "CHANGE_PASSWORD"
            assert super_client.get("/api/v1/auth/me").status_code == 403
            response = _write(super_client, "POST", "/api/v1/auth/password", {
                "current_password": "admin123", "new_password": "Twelve!123456", "new_password_confirm": "Twelve!123456",
            }, restricted_csrf)
            assert response.status_code == 200
            assert super_client.get("/api/v1/auth/me").status_code == 401

            response = _write(super_client, "POST", "/api/v1/auth/login", {"username": "admin", "password": "Twelve!123456"})
            super_csrf = response.json()["data"]["csrf_token"]
            assert response.json()["data"]["session_phase"] == "FULL"
            response = super_client.get("/api/v1/detections")
            assert response.status_code == 200
            assert response.json()["data"] == {"items": [], "page": 1, "page_size": 20, "total": 0}

            # 超级管理员按“创建 USER → 提升”流程创建管理员。
            response = _write(super_client, "POST", "/api/v1/admin/users", {
                "username": "alice_01", "display_name": "Alice", "temporary_password": "AliceSecure!123",
            }, super_csrf)
            alice = response.json()["data"]
            assert alice["role"] == "USER" and alice["must_change_password"] is True
            super_csrf = _csrf(super_client)
            response = _write(super_client, "PUT", f"/api/v1/admin/users/{alice['id']}/role", {"role": "ADMIN", "expected_version": alice["version"]}, super_csrf)
            assert response.status_code == 200

            # 群聊写操作需要幂等键；前端必须按此协议提交，成功后会出现在创建者会话列表。
            super_csrf = _csrf(super_client)
            response = super_client.post("/api/v1/admin/chat/groups", json={"title": "联调群", "member_ids": [alice["id"]]}, headers={
                "Origin": ORIGIN, "X-CSRF-Token": super_csrf, "Idempotency-Key": str(uuid4()),
            })
            assert response.status_code == 201
            group = response.json()["data"]
            assert group["title"] == "联调群" and group["member_count"] == 2
            conversations = super_client.get("/api/v1/chat/conversations").json()["data"]["items"]
            assert any(item["id"] == group["id"] and item["type"] == "GROUP" for item in conversations)

            # 已登录普通用户被停用后，旧会话不能继续读取个人资料。
            response = _write(bob_client, "POST", "/api/v1/auth/login", {"username": "bob_01", "password": "BobSecure!12345"})
            assert response.status_code == 200
            users = super_client.get("/api/v1/admin/users").json()["data"]["items"]
            bob = next(user for user in users if user["username"] == "bob_01")
            super_csrf = _csrf(super_client)
            response = _write(super_client, "PUT", f"/api/v1/admin/users/{bob['id']}/status", {"status": "DISABLED", "expected_version": bob["version"]}, super_csrf)
            assert response.status_code == 200
            assert bob_client.get("/api/v1/auth/me").status_code == 401
    finally:
        db_session.SessionLocal.configure(bind=old_bind)
        get_settings().database_url = old_url
        engine.dispose()
