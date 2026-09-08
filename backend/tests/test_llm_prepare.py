import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event

from app.core.config import get_settings
from app.db import session as db_session
from app.main import create_app
from app.models import LlmSettings, ProviderConfig
from app.models.extension import AgentProfile
from app.services.llm import encrypt_secret, secret_fingerprint, validation_fingerprint
from app.services import llm


ORIGIN = "http://127.0.0.1:8000"


def _configure_test_database(path: Path):
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
    return client.get("/api/v1/auth/csrf").json()["data"]["csrf_token"]


def _write(client: TestClient, method: str, path: str, payload: dict, csrf: str | None = None, **headers):
    return client.request(method, path, json=payload, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf or _csrf(client), **headers})


def test_prepare_previews_text_without_calling_cloud(tmp_path: Path) -> None:
    old_url, old_bind, engine = _configure_test_database(tmp_path / "llm.db")
    try:
        with TestClient(create_app(), base_url=ORIGIN) as client:
            response = _write(client, "POST", "/api/v1/auth/register", {
                "username": "llm_user", "display_name": "LLM User", "password": "LLMUserSecure!123", "password_confirm": "LLMUserSecure!123",
            })
            assert response.status_code == 201
            response = _write(client, "POST", "/api/v1/auth/login", {"username": "llm_user", "password": "LLMUserSecure!123"})
            assert response.status_code == 200

            # A deliberately non-routable URL is safe here: prepare must never
            # contact it. The config is seeded as previously validated.
            with db_session.SessionLocal.begin() as db:
                config = ProviderConfig(provider="DEEPSEEK", name="测试服务", base_url="https://api.deepseek.com",
                    model="test-model", api_key_encrypted=encrypt_secret("test-key"), api_key_fingerprint=secret_fingerprint("test-key"), enabled=True)
                db.add(config)
                db.flush()
                config.capabilities={"supports_stream":False,"supports_temperature":True,"temperature_min":0,"temperature_max":2}
                config.validation_fingerprint = validation_fingerprint(config)
                agent=AgentProfile(name="测试角色",business_prompt="实训文本帮助",temperature=0.7,provider_config_id=config.id,status="ACTIVE")
                db.add(agent);db.flush();agent_id=agent.id
                db.add(LlmSettings(id=1, default_provider_config_id=config.id))

            response = _write(client, "POST", "/api/v1/assistant/conversations", {"title": "仅本人的会话"}, **{"Idempotency-Key": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"})
            assert response.status_code == 201
            conversation_id = response.json()["data"]["id"]
            response = _write(client, "POST", "/api/v1/assistant/requests/prepare", {
                "conversation_id": conversation_id, "mode": "GENERAL", "question": "请说明检测结果与身份确认的区别。", "agent_profile_id":agent_id,
            }, **{"Idempotency-Key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"})
            assert response.status_code == 201
            prepared = response.json()["data"]
            assert prepared["state"] == "PREPARED"
            assert prepared["requires_consent"] is True
            assert "身份确认" in prepared["outbound_preview"]["question"]
            assert prepared["warning_codes"] == ["CLOUD_TEXT_TRANSFER", "GENERATED_CONTENT"]
    finally:
        db_session.SessionLocal.configure(bind=old_bind)
        get_settings().database_url = old_url
        engine.dispose()


def test_non_stream_qwen3_disables_thinking(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The non-streaming request must match the existing Qwen3 stream setting."""
    captured: dict = {}

    class DummyResponse:
        status_code = 200
        headers = {"x-request-id": "local-test-request"}

        @staticmethod
        def json() -> dict:
            return {"choices": [{"message": {"content": "安全答复"}, "finish_reason": "stop"}]}

    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *args) -> None:  # type: ignore[no-untyped-def]
            return None

        async def post(self, _endpoint: str, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return DummyResponse()

    monkeypatch.setattr(llm, "verify_public_dns", lambda _url: None)
    monkeypatch.setattr(llm, "decrypt_secret", lambda _value: "test-key")
    monkeypatch.setattr(llm.httpx, "AsyncClient", DummyClient)
    config = SimpleNamespace(
        provider="QWEN", base_url="https://dashscope.aliyuncs.com", model="qwen3-test",
        api_key_encrypted="ciphertext", max_output_tokens=64, temperature=0.7,
        timeout_seconds=2, capabilities={"supports_stream": False},
    )

    result = asyncio.run(llm.provider_generate(config, [{"role": "user", "content": "测试"}]))

    assert result["text"] == "安全答复"
    assert captured["json"]["enable_thinking"] is False
