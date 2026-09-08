import asyncio
import logging
import time
from uuid import uuid4

from app.db.sqlite_driver import ensure_sqlite_runtime

ensure_sqlite_runtime()

import anyio
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import api_error_handler, unhandled_error_handler, validation_error_handler
from app.services.security import ApiError, now, validate_session
from app.core.lifecycle import lifespan
from app.core.logging import configure_logging
from app.api.events import event_hub, send_event
from app.db.session import SessionLocal
from app.models import AuthSession


def websocket_user(raw_cookie: str | None) -> str | None:
    """Validate the current server-side session without trusting client data."""
    if not raw_cookie:
        return None
    from sqlalchemy import select
    from app.services.security import secret_hash

    with SessionLocal() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == secret_hash(raw_cookie)))
        if session is None:
            return None
        user = validate_session(session, require_full=True)
        if user is None:
            return None
        return user.id


def create_app() -> FastAPI:
    logger = configure_logging()
    app = FastAPI(
        title="海关视觉智能识别系统 API",
        version="1.2.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.error("request_failed request_id=%s method=%s", request.state.request_id, request.method)
            raise
        safe_route=getattr(request.scope.get("route"),"path","unmatched")
        logger.info("request request_id=%s method=%s route=%s status=%s duration_ms=%s", request.state.request_id, request.method, safe_route, response.status_code, round((time.perf_counter() - started) * 1000, 1))
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="same-origin"
        frame_ancestors = "'self'" if request.url.path.startswith("/ui/intro/") else "'none'"
        response.headers["Content-Security-Policy"]=f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; media-src 'self' blob:; frame-src 'self'; object-src 'none'; frame-ancestors {frame_ancestors}"
        response.headers["Cache-Control"]="private,no-store"
        if request.url.path.startswith("/api/v1/") and (response.status_code>=400 or request.method not in {"GET","HEAD","OPTIONS"}):
            from app.models.extension import OperationLog
            route=getattr(request.scope.get("route"),"path","unknown")
            try:
                with SessionLocal.begin() as log_db:
                    segments=route.strip('/').split('/')
                    if segments[:2]==['api','v1']:segments=segments[2:]
                    log_db.add(OperationLog(level="ERROR" if response.status_code>=500 else "WARN" if response.status_code>=400 else "INFO",module=segments[0] if segments else "api",event_code="HTTP_ERROR" if response.status_code>=400 else "WRITE_COMPLETED",request_id=request.state.request_id,safe_context={"route":route,"method":request.method,"status":response.status_code,"duration_ms":round((time.perf_counter()-started)*1000)}))
            except Exception:logger.error("operation_log_persist_failed request_id=%s",request.state.request_id)
        # 登录入口必须始终使用最新脚本，避免浏览器将旧的受限会话页面留在缓存中。
        if request.url.path in {"/", "/index.html", "/app.js", "/styles.css", "/auth-background.css"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(api_router)

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        # Browsers may send cookies on a cross-site WS upgrade, hence Origin is
        # mandatory even though the session itself is HttpOnly.
        if websocket.headers.get("origin") not in get_settings().origin_set:
            await websocket.close(code=1008)
            return
        try:
            user_id = await anyio.to_thread.run_sync(websocket_user, websocket.cookies.get("customs_session"))
        except ApiError:
            await websocket.close(code=1008)
            return
        if user_id is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        queue = await event_hub.connect(user_id)
        try:
            await send_event(websocket, "connection.ready", {"connection_id": str(uuid4()), "heartbeat_seconds": 30})
            while True:
                outgoing = asyncio.create_task(queue.get())
                incoming = asyncio.create_task(websocket.receive_json())
                timeout = asyncio.create_task(asyncio.sleep(30))
                done, pending = await asyncio.wait({outgoing, incoming, timeout}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if outgoing in done:
                    event = outgoing.result()
                    await websocket.send_json(event)
                    if event["type"] == "session.revoked":
                        await websocket.close(code=4003)
                        return
                elif incoming in done:
                    frame = incoming.result()
                    # The protocol accepts no subscriptions or user-directed
                    # events: only a matching pong is meaningful.
                    if not isinstance(frame, dict) or frame.get("type") != "pong":
                        await websocket.close(code=1008)
                        return
                else:
                    nonce = str(uuid4())
                    await send_event(websocket, "ping", {"nonce": nonce})
                    try:
                        frame = await asyncio.wait_for(websocket.receive_json(), timeout=10)
                    except TimeoutError:
                        await websocket.close(code=4001)
                        return
                    if not isinstance(frame, dict) or frame.get("type") != "pong" or frame.get("nonce") != nonce:
                        await websocket.close(code=4001)
                        return
                # Revalidate after every application interaction / heartbeat so
                # status and permission revocations cannot linger in a socket.
                try:
                    current = await anyio.to_thread.run_sync(websocket_user, websocket.cookies.get("customs_session"))
                except ApiError:
                    current = None
                if current != user_id:
                    await websocket.close(code=4001)
                    return
        except WebSocketDisconnect:
            return
        finally:
            await event_hub.disconnect(user_id, queue)

    @app.get("/health", include_in_schema=False)
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    frontend_root = get_settings().frontend_root.resolve()
    if (frontend_root / "index.html").is_file():
        @app.get("/",include_in_schema=False)
        async def frontend_index():return FileResponse(frontend_root/"index.html")
        @app.get("/{filename}",include_in_schema=False)
        async def frontend_file(filename:str):
            if filename not in {"index.html","frontend.js","frontend.css","markdown.js","avatar.js"}:raise ApiError(404,"NOT_FOUND","资源不存在")
            return FileResponse(frontend_root/filename)
        if (frontend_root/"assets").is_dir():app.mount("/assets",StaticFiles(directory=frontend_root/"assets"),name="assets")
        if (frontend_root/"vendor").is_dir():app.mount("/vendor",StaticFiles(directory=frontend_root/"vendor"),name="vendor")
        if (frontend_root/"ui").is_dir():app.mount("/ui",StaticFiles(directory=frontend_root/"ui"),name="ui")
    return app


app = create_app()
