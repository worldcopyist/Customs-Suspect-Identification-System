"""密码、会话、CSRF 与服务端授权。"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import ipaddress
import secrets
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import AuthSession, Role, SessionPhase, User, UserStatus

password_hasher = PasswordHasher()


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def now() -> datetime:
    return datetime.now(UTC)


def secret_hash(value: str) -> str:
    key = get_settings().app_secret_key.encode()
    return hmac.new(key, value.encode(), sha256).hexdigest()


def password_hash(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_session(db: Session, user: User | None = None, phase: SessionPhase = SessionPhase.ANONYMOUS) -> tuple[AuthSession, str, str]:
    settings = get_settings()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    issued = now()
    seconds = settings.restricted_session_seconds if phase != SessionPhase.FULL else settings.session_absolute_seconds
    session = AuthSession(
        token_hash=secret_hash(token), csrf_hash=secret_hash(csrf), user_id=user.id if user else None,
        phase=phase.value, issued_at=issued, expires_at=issued + timedelta(seconds=seconds), last_seen_at=issued,
    )
    db.add(session)
    return session, token, csrf


def revoke_user_sessions(db: Session, user_id: str) -> None:
    db.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)).values(revoked_at=now()))


def session_from_request(request: Request, db: Session) -> AuthSession | None:
    raw = request.cookies.get("customs_session")
    if not raw:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == secret_hash(raw)))
    if session is None:
        return None
    return session


def validate_session(session: AuthSession, require_full: bool = False) -> User | None:
    current = now()
    if session.revoked_at is not None:
        raise ApiError(401, "SESSION_REVOKED", "登录状态已失效，请重新登录")
    absolute = session.expires_at.replace(tzinfo=UTC)
    if session.phase == SessionPhase.FULL.value:
        absolute = min(absolute, session.issued_at.replace(tzinfo=UTC) + timedelta(seconds=get_settings().session_absolute_seconds))
    if absolute <= current:
        raise ApiError(401, "SESSION_EXPIRED", "登录状态已过期，请重新登录")
    if (
        session.phase == SessionPhase.FULL.value
        and session.last_seen_at.replace(tzinfo=UTC) + timedelta(seconds=get_settings().session_idle_seconds) <= current
    ):
        raise ApiError(401, "SESSION_EXPIRED", "登录状态因长时间未操作而过期")
    user = session.user
    if require_full and user is None:
        raise ApiError(401,"UNAUTHENTICATED","请先登录")
    if user is not None and user.status != UserStatus.ACTIVE.value:
        raise ApiError(403, "ACCOUNT_DISABLED", "账户已停用")
    if require_full and session.phase != SessionPhase.FULL.value:
        raise ApiError(403, "PASSWORD_CHANGE_REQUIRED", "请先修改初始密码")
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    session = session_from_request(request, db)
    if session is None:
        raise ApiError(401, "UNAUTHENTICATED", "请先登录")
    user = validate_session(session, require_full=True)
    if user is None:
        raise ApiError(401, "UNAUTHENTICATED", "请先登录")
    request.state.actor_id = user.id
    # Polling, presence and SSE must not make an idle background page immortal.
    if request.headers.get("X-Background-Request") != "true" and request.url.path != "/api/v1/presence/heartbeat" and not request.url.path.endswith("/events"):
        session.last_seen_at = now()
        db.commit()
    return user


def require_session(request: Request, db: Session = Depends(get_db)) -> tuple[AuthSession, User]:
    session = session_from_request(request, db)
    if session is None:
        raise ApiError(401, "UNAUTHENTICATED", "请先登录")
    user = validate_session(session)
    if user is None:
        raise ApiError(401, "UNAUTHENTICATED", "请先登录")
    return session, user


def require_csrf(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    session = session_from_request(request, db)
    if session is None:
        raise ApiError(401, "UNAUTHENTICATED", "请先获取 CSRF 令牌")
    validate_session(session)
    origin = request.headers.get("origin")
    if not allowed_origin(origin):
        raise ApiError(403, "ORIGIN_NOT_ALLOWED", "请求来源不受信任")
    token = request.headers.get("X-CSRF-Token", "")
    if not token or not hmac.compare_digest(session.csrf_hash, secret_hash(token)):
        raise ApiError(403, "CSRF_INVALID", "CSRF 令牌无效，请刷新后重试")
    return session


def allowed_origin(origin: str | None) -> bool:
    """LAN deployments explicitly configure their exact HTTPS origin."""
    return origin in get_settings().origin_set


def require_manager(user: User) -> None:
    if user.role not in {Role.ADMIN.value, Role.SUPER_ADMIN.value}:
        raise ApiError(403, "FORBIDDEN", "需要管理员权限")


def require_super_admin(user: User) -> None:
    if user.role != Role.SUPER_ADMIN.value:
        raise ApiError(403, "FORBIDDEN", "需要超级管理员权限")


def can_manage(actor: User, target: User) -> bool:
    if target.is_builtin:
        return False
    if actor.role == Role.SUPER_ADMIN.value:
        return target.role in {Role.USER.value, Role.ADMIN.value}
    return actor.role == Role.ADMIN.value and target.role == Role.USER.value


def set_session_cookie(response, token: str, expires_at: datetime) -> None:  # type: ignore[no-untyped-def]
    response.set_cookie(
        "customs_session", token, httponly=True, secure=get_settings().cookie_secure,
        samesite="strict", path="/", expires=expires_at,
    )


def clear_session_cookie(response) -> None:  # type: ignore[no-untyped-def]
    response.delete_cookie("customs_session", path="/")
