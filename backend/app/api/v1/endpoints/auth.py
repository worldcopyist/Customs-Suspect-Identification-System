"""认证、Cookie 会话、CSRF 与个人资料。"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import request_id
from app.db.session import get_db
from app.models import Role, SessionPhase, User, UserStatus
from app.schemas.auth import (
    ChangePasswordIn, CsrfOut, LoginIn, LoginOut, RegisterIn, UpdateMeIn, UserOut, DEFAULT_PERMISSIONS, validate_password,
)
from app.schemas.common import SuccessResponse
from app.services.business import audit,version
from app.services.security import (
    ApiError, clear_session_cookie, new_session, now, password_hash, require_csrf, require_session, require_user,
    revoke_user_sessions, session_from_request, set_session_cookie, verify_password, validate_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


def csrf_response(request: Request, session, token: str) -> SuccessResponse[CsrfOut]:
    return SuccessResponse(data=CsrfOut(csrf_token=token, expires_at=session.expires_at), request_id=request_id(request))


@router.get("/csrf", response_model=SuccessResponse[CsrfOut])
def csrf(request: Request, response: Response, db: Session = Depends(get_db)) -> SuccessResponse[CsrfOut]:
    session = session_from_request(request, db)
    raw_token: str | None = None
    if session is not None:
        try:
            validate_session(session)
        except ApiError:
            session = None
    if session is None or session.revoked_at is not None or session.expires_at.replace(tzinfo=now().tzinfo) <= now():
        session, raw_token, csrf_token = new_session(db)
    else:
        import secrets
        from app.services.security import secret_hash
        csrf_token = secrets.token_urlsafe(32)
        session.csrf_hash = secret_hash(csrf_token)
    db.commit()
    if raw_token:
        set_session_cookie(response, raw_token, session.expires_at)
    return csrf_response(request, session, csrf_token)


@router.post("/register", status_code=201, response_model=SuccessResponse[dict])
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    username = payload.username.lower()
    if username == "admin":
        raise ApiError(422, "RESERVED_USERNAME", "admin 是保留用户名")
    if db.scalar(select(User).where(User.username == username)):
        raise ApiError(409, "USERNAME_EXISTS", "用户名已存在")
    user = User(
        username=username, display_name=payload.display_name, password_hash=password_hash(payload.password),
        role=Role.USER.value, permissions=sorted(DEFAULT_PERMISSIONS),
    )
    db.add(user)
    db.flush()
    audit(db,request,user,'USER_REGISTERED','USER',user.id)
    db.commit()
    return SuccessResponse(data={"id": user.id, "username": user.username, "role": Role.USER.value}, request_id=request_id(request))


@router.post("/login", response_model=SuccessResponse[LoginOut])
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> SuccessResponse[LoginOut]:
    require_csrf(request, db)
    username = payload.username.lower()
    user = db.scalar(select(User).where(User.username == username))
    if user is None or user.status == UserStatus.DELETED.value or not verify_password(payload.password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    if user.status != UserStatus.ACTIVE.value:
        raise ApiError(403, "ACCOUNT_DISABLED", "账户已停用")
    if payload.portal == "ADMIN" and user.role == "USER":
        raise ApiError(403, "PORTAL_FORBIDDEN", "普通用户不能进入管理端，请选择用户端")
    old = session_from_request(request, db)
    if old is not None:
        old.revoked_at = now()
    phase = SessionPhase.CHANGE_PASSWORD if user.must_change_password else SessionPhase.FULL
    session, raw_token, csrf_token = new_session(db, user, phase)
    audit(db,request,user,'LOGIN_SUCCEEDED','USER',user.id,after={'portal':payload.portal})
    db.commit()
    set_session_cookie(response, raw_token, session.expires_at)
    profile=user_out(user)
    if phase == SessionPhase.CHANGE_PASSWORD:profile.permissions=[]
    return SuccessResponse(
        data=LoginOut(user=profile, session_phase=phase.value, csrf_token=csrf_token, expires_at=session.expires_at),
        request_id=request_id(request),
    )


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    session = session_from_request(request, db)
    if session is not None:
        # 过期状态退出也应幂等清 Cookie；若携带有效会话则仍执行 CSRF 校验。
        if session.revoked_at is None and session.expires_at.replace(tzinfo=now().tzinfo) > now():
            require_csrf(request, db)
        session.revoked_at = now()
        db.commit()
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=SuccessResponse[UserOut])
def me(request: Request, user: User = Depends(require_user)) -> SuccessResponse[UserOut]:
    return SuccessResponse(data=user_out(user), request_id=request_id(request))


@router.patch("/me", response_model=SuccessResponse[UserOut])
def update_me(payload: UpdateMeIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> SuccessResponse[UserOut]:
    require_csrf(request, db)
    version(db,user,payload.expected_version)
    user.display_name = payload.display_name
    audit(db,request,user,'PROFILE_UPDATED','USER',user.id)
    db.commit()
    return SuccessResponse(data=user_out(user), request_id=request_id(request))


@router.post("/password", response_model=SuccessResponse[dict])
def change_password(payload: ChangePasswordIn, request: Request, db: Session = Depends(get_db)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    session, user = require_session(request, db)
    if not verify_password(payload.current_password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "当前密码错误")
    validate_password(payload.new_password, user.username)
    if payload.new_password == payload.current_password:
        raise ApiError(422, "PASSWORD_POLICY", "新密码不能与旧密码相同")
    user.password_hash = password_hash(payload.new_password)
    user.must_change_password = False
    user.version += 1
    revoke_user_sessions(db, user.id)
    # 本次请求完成后也必须重新认证，不保留能够继续使用的会话。
    session.revoked_at = now()
    audit(db,request,user,'PASSWORD_CHANGED','USER',user.id)
    db.commit()
    return SuccessResponse(data={"password_changed": True, "reauthentication_required": True}, request_id=request_id(request))
