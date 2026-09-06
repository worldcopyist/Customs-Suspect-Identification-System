"""管理员账户管理与服务端角色/功能授权边界。"""

import json

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import request_id
from app.db.session import get_db
from app.models import AuditLog, Role, User, UserStatus
from app.schemas.auth import (
    CreateUserIn, DEFAULT_PERMISSIONS, PermissionsIn, ResetPasswordIn, RoleIn, StatusIn, UpdateUserIn, UserOut,
)
from app.schemas.common import SuccessResponse
from app.services.security import (
    ApiError, can_manage, password_hash, require_csrf, require_manager, require_super_admin, require_user,
    revoke_user_sessions,
)

router = APIRouter(prefix="/admin/users", tags=["users"])


def to_user(user: User) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


def audit(db: Session, actor: User, target: User, action: str, **details: str) -> None:
    db.add(AuditLog(actor_id=actor.id, target_user_id=target.id, action=action, details=json.dumps(details, ensure_ascii=False)))


def target_or_404(db: Session, actor: User, user_id: str) -> User:
    target = db.get(User, user_id)
    # 对不在管理范围内的目标返回 404，不暴露同级管理员或内置账户资料。
    if target is None or not can_manage(actor, target):
        raise ApiError(404, "NOT_FOUND", "用户不存在或不可管理")
    return target


def check_version(target: User, expected: int) -> None:
    if target.version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "用户资料已更新，请刷新后重试", {"current_version": target.version})


@router.get("", response_model=SuccessResponse[dict])
def list_users(
    request: Request, page: int = 1, page_size: int = 20, q: str | None = None,
    status: UserStatus | None = None, role: Role | None = None,
    db: Session = Depends(get_db), actor: User = Depends(require_user),
) -> SuccessResponse[dict]:
    require_manager(actor)
    if not 1 <= page or not 1 <= page_size <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "分页参数不合法")
    allowed_roles = [Role.USER.value] if actor.role == Role.ADMIN.value else [Role.USER.value, Role.ADMIN.value]
    statement = select(User).where(User.role.in_(allowed_roles), User.status != UserStatus.DELETED.value)
    if q:
        needle = f"%{q.strip()}%"
        statement = statement.where(or_(User.username.like(needle), User.display_name.like(needle)))
    if status:
        statement = statement.where(User.status == status.value)
    if role:
        if role.value not in allowed_roles:
            return SuccessResponse(data={"items": [], "page": page, "page_size": page_size, "total": 0}, request_id=request_id(request))
        statement = statement.where(User.role == role.value)
    users = list(db.scalars(statement.order_by(User.created_at.desc(), User.id.desc())))
    total = len(users)
    window = users[(page - 1) * page_size : page * page_size]
    return SuccessResponse(
        data={"items": [to_user(item).model_dump(mode="json") for item in window], "page": page, "page_size": page_size, "total": total},
        request_id=request_id(request),
    )


@router.get("/{user_id}", response_model=SuccessResponse[UserOut])
def get_user(user_id: str, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[UserOut]:
    require_manager(actor)
    return SuccessResponse(data=to_user(target_or_404(db, actor, user_id)), request_id=request_id(request))


@router.post("", status_code=201, response_model=SuccessResponse[UserOut])
def create_user(payload: CreateUserIn, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[UserOut]:
    require_csrf(request, db)
    require_manager(actor)
    if payload.username == "admin":
        raise ApiError(422, "RESERVED_USERNAME", "admin 是保留用户名")
    if db.scalar(select(User).where(User.username == payload.username)):
        raise ApiError(409, "USERNAME_EXISTS", "用户名已存在")
    target = User(
        username=payload.username, display_name=payload.display_name, password_hash=password_hash(payload.temporary_password),
        role=Role.USER.value, permissions=sorted(DEFAULT_PERMISSIONS), must_change_password=True,
    )
    db.add(target)
    db.flush()
    audit(db, actor, target, "USER_CREATED")
    db.commit()
    return SuccessResponse(data=to_user(target), request_id=request_id(request))


@router.patch("/{user_id}", response_model=SuccessResponse[UserOut])
def update_user(user_id: str, payload: UpdateUserIn, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[UserOut]:
    require_csrf(request, db)
    require_manager(actor)
    target = target_or_404(db, actor, user_id)
    check_version(target, payload.expected_version)
    target.display_name = payload.display_name
    target.version += 1
    audit(db, actor, target, "USER_PROFILE_UPDATED")
    db.commit()
    return SuccessResponse(data=to_user(target), request_id=request_id(request))


@router.put("/{user_id}/status", response_model=SuccessResponse[UserOut])
def update_status(user_id: str, payload: StatusIn, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[UserOut]:
    require_csrf(request, db)
    require_manager(actor)
    target = target_or_404(db, actor, user_id)
    check_version(target, payload.expected_version)
    target.status = payload.status
    target.version += 1
    revoke_user_sessions(db, target.id)
    audit(db, actor, target, "USER_STATUS_UPDATED", status=payload.status)
    db.commit()
    return SuccessResponse(data=to_user(target), request_id=request_id(request))


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: str, request: Request, response: Response, if_match: str | None = Header(default=None),
    db: Session = Depends(get_db), actor: User = Depends(require_user),
) -> Response:
    require_csrf(request, db)
    require_manager(actor)
    if not if_match or not if_match.startswith('"v') or not if_match.endswith('"') or not if_match[2:-1].isdigit():
        raise ApiError(428, "VERSION_REQUIRED", "删除操作需要 If-Match 版本")
    target = target_or_404(db, actor, user_id)
    check_version(target, int(if_match[2:-1]))
    target.status = UserStatus.DELETED.value
    target.version += 1
    revoke_user_sessions(db, target.id)
    audit(db, actor, target, "USER_DELETED")
    db.commit()
    return response


@router.put("/{user_id}/role", response_model=SuccessResponse[UserOut])
def update_role(user_id: str, payload: RoleIn, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[UserOut]:
    require_csrf(request, db)
    require_super_admin(actor)
    target = target_or_404(db, actor, user_id)
    check_version(target, payload.expected_version)
    old_role = target.role
    target.role = payload.role
    if payload.role == Role.USER.value:
        target.permissions = sorted(DEFAULT_PERMISSIONS)
    target.version += 1
    revoke_user_sessions(db, target.id)
    audit(db, actor, target, "USER_ROLE_UPDATED", old_role=old_role, new_role=payload.role)
    db.commit()
    return SuccessResponse(data=to_user(target), request_id=request_id(request))


@router.put("/{user_id}/permissions", response_model=SuccessResponse[UserOut])
def update_permissions(user_id: str, payload: PermissionsIn, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[UserOut]:
    require_csrf(request, db)
    require_manager(actor)
    target = target_or_404(db, actor, user_id)
    if target.role != Role.USER.value:
        raise ApiError(404, "NOT_FOUND", "用户不存在或不可管理")
    check_version(target, payload.expected_version)
    target.permissions = payload.permissions
    target.version += 1
    revoke_user_sessions(db, target.id)
    audit(db, actor, target, "USER_PERMISSIONS_UPDATED")
    db.commit()
    return SuccessResponse(data=to_user(target), request_id=request_id(request))


@router.post("/{user_id}/password-reset", response_model=SuccessResponse[dict])
def reset_password(user_id: str, payload: ResetPasswordIn, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    require_manager(actor)
    target = target_or_404(db, actor, user_id)
    check_version(target, payload.expected_version)
    from app.schemas.auth import validate_password
    validate_password(payload.temporary_password, target.username)
    target.password_hash = password_hash(payload.temporary_password)
    target.must_change_password = True
    target.version += 1
    revoke_user_sessions(db, target.id)
    audit(db, actor, target, "USER_PASSWORD_RESET")
    db.commit()
    return SuccessResponse(data={"reset": True, "must_change_password": True, "version": target.version}, request_id=request_id(request))
