"""Private and group text communication; message content is REST-only."""

import hashlib
import json
from datetime import UTC, timedelta
from uuid import UUID

import anyio
from anyio.from_thread import run as run_from_thread
from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from app.api.events import event_hub
from app.core.errors import request_id
from app.db.session import get_db
from app.models import (
    AuditLog, ChatMessage, Conversation, ConversationMember, ConversationState, ConversationType,
    IdempotencyRecord, MembershipState, Role, User, UserStatus,
)
from app.schemas.chat import (
    AddMembersIn, ConversationOut, CreateGroupIn, DirectConversationIn, DissolveGroupIn, GroupOut,
    MemberOut, MessageOut, MessagePageOut, ReadConversationIn, SendMessageIn, UpdateGroupIn, UserDirectoryOut,
)
from app.schemas.common import SuccessResponse
from app.services.security import ApiError, now, require_csrf, require_manager, require_user

router = APIRouter(prefix="/chat", tags=["chat"])
admin_router = APIRouter(prefix="/admin/chat", tags=["chat-admin"])


def require_chat_permission(user: User) -> None:
    if user.role == Role.USER.value and "chat.use" not in user.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "没有内部通讯权限")


def active_member_or_404(db: Session, conversation_id: str, user_id: str) -> ConversationMember:
    member = db.scalar(select(ConversationMember).where(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id,
        ConversationMember.state == MembershipState.ACTIVE.value,
    ))
    if member is None:
        raise ApiError(404, "NOT_FOUND", "会话不存在或当前不可见")
    return member


def conversation_or_404(db: Session, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ApiError(404, "NOT_FOUND", "会话不存在")
    return conversation


def active_member_count(db: Session, conversation_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(ConversationMember).where(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.state == MembershipState.ACTIVE.value,
    )) or 0)


def to_user(user: User) -> UserDirectoryOut:
    return UserDirectoryOut(id=user.id, username=user.username, display_name=user.display_name)


def to_member(member: ConversationMember, user: User) -> MemberOut:
    return MemberOut(**to_user(user).model_dump(), state=member.state, joined_at=member.joined_at, removed_at=member.removed_at)


def to_conversation(db: Session, conversation: Conversation, member: ConversationMember, viewer: User) -> ConversationOut:
    title = conversation.title
    if conversation.type == ConversationType.DIRECT.value:
        peer = db.scalar(select(User).join(ConversationMember, ConversationMember.user_id == User.id).where(
            ConversationMember.conversation_id == conversation.id,
            ConversationMember.user_id != viewer.id,
        ))
        title = peer.display_name if peer else "已删除用户"
    return ConversationOut(
        id=conversation.id, type=conversation.type, title=title, state=conversation.state,
        member_count=active_member_count(db, conversation.id), last_seq=str(conversation.last_seq),
        last_read_seq=str(member.last_read_seq), unread_count=max(0, conversation.last_seq - member.last_read_seq),
        version=conversation.version,
    )


def to_group(db: Session, conversation: Conversation) -> GroupOut:
    return GroupOut(id=conversation.id, title=conversation.title, state=conversation.state,
                    member_count=active_member_count(db, conversation.id), created_by=conversation.created_by,
                    version=conversation.version, created_at=conversation.created_at, dissolved_at=conversation.dissolved_at)


def to_message(message: ChatMessage) -> MessageOut:
    return MessageOut(id=message.id, conversation_id=message.conversation_id, sender_id=message.sender_id,
                      sender_display_name=message.sender_display_name, seq=str(message.seq),
                      client_message_id=message.client_message_id, content=message.content, created_at=message.created_at)


def canonical_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def idempotency_replay(
    db: Session, user: User, request: Request, key: str | None, payload: object,
) -> IdempotencyRecord | None:
    if key is None:
        raise ApiError(422, "VALIDATION_ERROR", "该操作需要 Idempotency-Key")
    try:
        UUID(key)
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "Idempotency-Key 必须为 UUID") from exc
    record = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user.id, IdempotencyRecord.method == request.method,
        IdempotencyRecord.path == request.url.path, IdempotencyRecord.key == key,
    ))
    if record is not None and record.created_at.replace(tzinfo=UTC) <= now() - timedelta(hours=24):
        # The unique scope is intentionally released after the contractual
        # replay window instead of retaining stale successful operations forever.
        db.delete(record)
        db.flush()
        record = None
    if record and record.request_hash != canonical_hash(payload):
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键不能提交不同内容")
    return record


def remember_idempotency(db: Session, user: User, request: Request, key: str, payload: object, status: int, data: dict) -> None:
    db.add(IdempotencyRecord(user_id=user.id, method=request.method, path=request.url.path, key=key,
                             request_hash=canonical_hash(payload), response_status=status, response_data=jsonable_encoder(data)))


def emit(user_ids: list[str], event_type: str, data: dict) -> None:
    # Optional notifications must never turn an already committed group/message into HTTP 500.
    try:
        run_from_thread(event_hub.publish, user_ids, event_type, data)
    except Exception:
        import logging
        logging.getLogger("customs_training").error("chat_notification_failed event_type=%s",event_type)


def audit_group(db: Session, actor: User, conversation: Conversation, action: str, **details: object) -> None:
    """Keep group administration accountable without logging any message body."""
    db.add(AuditLog(actor_id=actor.id, target_user_id=None, action=action,
                    details=json.dumps({"conversation_id": conversation.id, **details}, ensure_ascii=False)))


@router.get("/users", response_model=SuccessResponse[dict])
def list_users(request: Request, page: int = 1, page_size: int = 20, q: str | None = None,
               db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_chat_permission(actor)
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "分页参数不合法")
    statement = select(User).where(User.status == UserStatus.ACTIVE.value, User.id != actor.id)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        statement = statement.where((User.username.like(needle)) | (User.display_name.like(needle)))
    users = list(db.scalars(statement.order_by(User.created_at.desc(), User.id.desc())))
    return SuccessResponse(data={"items": [to_user(item).model_dump(mode="json") for item in users[(page - 1) * page_size:page * page_size]], "page": page, "page_size": page_size, "total": len(users)}, request_id=request_id(request))


@router.get("/conversations", response_model=SuccessResponse[dict])
def list_conversations(request: Request, page: int = 1, page_size: int = 20,
                       db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_chat_permission(actor)
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "分页参数不合法")
    rows = list(db.execute(select(Conversation, ConversationMember).join(ConversationMember).where(
        ConversationMember.user_id == actor.id, ConversationMember.state == MembershipState.ACTIVE.value,
    ).order_by(Conversation.created_at.desc(), Conversation.id.desc())).all())
    window = rows[(page - 1) * page_size:page * page_size]
    return SuccessResponse(data={"items": [to_conversation(db, item, member, actor).model_dump(mode="json") for item, member in window], "page": page, "page_size": page_size, "total": len(rows)}, request_id=request_id(request))


@router.post("/direct-conversations", status_code=201, response_model=SuccessResponse[ConversationOut])
def create_direct(payload: DirectConversationIn, request: Request, response: Response,
                  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[ConversationOut]:
    require_csrf(request, db)
    require_chat_permission(actor)
    serialized = payload.model_dump(mode="json")
    replay = idempotency_replay(db, actor, request, idempotency_key, serialized)
    if replay:
        response.status_code = replay.response_status
        response.headers["Idempotency-Replayed"] = "true"
        return SuccessResponse(data=ConversationOut(**replay.response_data), request_id=request_id(request))
    peer_id = str(payload.peer_user_id)
    if peer_id == actor.id:
        raise ApiError(422, "SELF_CHAT_NOT_ALLOWED", "不能和自己建立私聊")
    peer = db.get(User, peer_id)
    if peer is None or peer.status != UserStatus.ACTIVE.value:
        raise ApiError(409, "USER_UNAVAILABLE", "目标用户当前不可用")
    direct_key = ":".join(sorted((actor.id, peer_id)))
    conversation = db.scalar(select(Conversation).where(Conversation.direct_key == direct_key))
    created = conversation is None
    if conversation is None:
        conversation = Conversation(type=ConversationType.DIRECT.value, direct_key=direct_key, created_by=actor.id)
        db.add(conversation)
        db.flush()
        db.add_all([ConversationMember(conversation_id=conversation.id, user_id=actor.id), ConversationMember(conversation_id=conversation.id, user_id=peer_id)])
        db.flush()
    member = active_member_or_404(db, conversation.id, actor.id)
    data = to_conversation(db, conversation, member, actor).model_dump(mode="json")
    remember_idempotency(db, actor, request, idempotency_key or "", serialized, 201 if created else 200, data)
    db.commit()
    if not created:
        response.status_code = 200
    return SuccessResponse(data=ConversationOut(**data), request_id=request_id(request))


@router.get("/conversations/{conversation_id}", response_model=SuccessResponse[ConversationOut])
def get_conversation(conversation_id: UUID, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[ConversationOut]:
    require_chat_permission(actor)
    cid = str(conversation_id)
    member = active_member_or_404(db, cid, actor.id)
    return SuccessResponse(data=to_conversation(db, conversation_or_404(db, cid), member, actor), request_id=request_id(request))


@router.get("/conversations/{conversation_id}/members", response_model=SuccessResponse[dict])
def conversation_members(conversation_id: UUID, request: Request, page: int = 1, page_size: int = 20,
                         db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_chat_permission(actor)
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "分页参数不合法")
    cid = str(conversation_id)
    active_member_or_404(db, cid, actor.id)
    rows = list(db.execute(select(ConversationMember, User).join(User).where(ConversationMember.conversation_id == cid, ConversationMember.state == MembershipState.ACTIVE.value).order_by(ConversationMember.joined_at, ConversationMember.id)).all())
    return SuccessResponse(data={"items": [to_member(member, user).model_dump(mode="json") for member, user in rows[(page - 1) * page_size:page * page_size]], "page": page, "page_size": page_size, "total": len(rows)}, request_id=request_id(request))


@router.get("/conversations/{conversation_id}/messages", response_model=SuccessResponse[MessagePageOut])
def list_messages(conversation_id: UUID, request: Request, after_seq: str | None = None, before_seq: str | None = None, limit: int = 50,
                  db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[MessagePageOut]:
    require_chat_permission(actor)
    if limit < 1 or limit > 100 or (after_seq is not None and before_seq is not None):
        raise ApiError(422, "INVALID_CURSOR", "消息游标不合法")
    if (after_seq is not None and (not after_seq.isdecimal() or len(after_seq) > 1 and after_seq.startswith("0"))) or (before_seq is not None and (not before_seq.isdecimal() or len(before_seq) > 1 and before_seq.startswith("0"))):
        raise ApiError(422, "INVALID_CURSOR", "消息游标必须是非负整数")
    after = int(after_seq) if after_seq is not None else None
    before = int(before_seq) if before_seq is not None else None
    cid = str(conversation_id)
    active_member_or_404(db, cid, actor.id)
    statement = select(ChatMessage).where(ChatMessage.conversation_id == cid)
    if after is not None:
        messages = list(db.scalars(statement.where(ChatMessage.seq > after).order_by(ChatMessage.seq).limit(limit + 1)))
        has_more = len(messages) > limit
        items = messages[:limit]
        page = MessagePageOut(items=[to_message(item) for item in items], has_more=has_more,
                              next_after_seq=str(items[-1].seq) if items else None, next_before_seq=None)
    elif before is not None:
        messages = list(db.scalars(statement.where(ChatMessage.seq < before).order_by(ChatMessage.seq.desc()).limit(limit + 1)))
        has_more = len(messages) > limit
        items = list(reversed(messages[:limit]))
        page = MessagePageOut(items=[to_message(item) for item in items], has_more=has_more, next_after_seq=None,
                              next_before_seq=str(items[0].seq) if items else None)
    else:
        messages = list(db.scalars(statement.order_by(ChatMessage.seq.desc()).limit(limit + 1)))
        has_more = len(messages) > limit
        items = list(reversed(messages[:limit]))
        page = MessagePageOut(items=[to_message(item) for item in items], has_more=has_more,
                              next_after_seq=str(items[-1].seq) if items else None,
                              next_before_seq=str(items[0].seq) if has_more and items else None)
    return SuccessResponse(data=page, request_id=request_id(request))


@router.post("/conversations/{conversation_id}/messages", status_code=201, response_model=SuccessResponse[MessageOut])
def send_message(conversation_id: UUID, payload: SendMessageIn, request: Request, response: Response,
                 db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[MessageOut]:
    require_csrf(request, db)
    require_chat_permission(actor)
    cid, client_id = str(conversation_id), str(payload.client_message_id)
    active_member_or_404(db, cid, actor.id)
    duplicate = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == cid, ChatMessage.client_message_id == client_id))
    if duplicate is not None:
        if duplicate.sender_id != actor.id or duplicate.content != payload.content:
            raise ApiError(409, "MESSAGE_ID_CONFLICT", "同一消息 ID 不能提交不同内容")
        response.status_code = 200
        return SuccessResponse(data=to_message(duplicate), request_id=request_id(request))
    membership_exists = exists(select(ConversationMember.id).where(
        ConversationMember.conversation_id == Conversation.id, ConversationMember.user_id == actor.id,
        ConversationMember.state == MembershipState.ACTIVE.value,
    ))
    seq = db.scalar(update(Conversation).where(
        Conversation.id == cid, Conversation.state == ConversationState.ACTIVE.value, membership_exists,
    ).values(last_seq=Conversation.last_seq + 1).returning(Conversation.last_seq))
    if seq is None:
        conversation = conversation_or_404(db, cid)
        if conversation.state != ConversationState.ACTIVE.value:
            raise ApiError(409, "CONVERSATION_READ_ONLY", "会话已只读")
        raise ApiError(404, "NOT_FOUND", "会话不存在或当前不可见")
    message = ChatMessage(conversation_id=cid, sender_id=actor.id, sender_display_name=actor.display_name,
                          seq=seq, client_message_id=client_id, content=payload.content)
    db.add(message)
    db.flush()
    recipients = list(db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == cid, ConversationMember.state == MembershipState.ACTIVE.value)))
    db.commit()
    emit(recipients, "chat.message.created", {"conversation_id": cid, "last_seq": str(seq)})
    return SuccessResponse(data=to_message(message), request_id=request_id(request))


@router.put("/conversations/{conversation_id}/read", response_model=SuccessResponse[dict])
def mark_read(conversation_id: UUID, payload: ReadConversationIn, request: Request,
              db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    require_chat_permission(actor)
    cid, requested = str(conversation_id), int(payload.last_read_seq)
    member = active_member_or_404(db, cid, actor.id)
    conversation = conversation_or_404(db, cid)
    if requested > conversation.last_seq:
        raise ApiError(422, "INVALID_READ_CURSOR", "已读游标超过当前消息")
    member.last_read_seq = max(member.last_read_seq, requested)
    db.commit()
    return SuccessResponse(data={"last_read_seq": str(member.last_read_seq), "unread_count": max(0, conversation.last_seq - member.last_read_seq)}, request_id=request_id(request))


def group_or_404(db: Session, conversation_id: str, active_only: bool = False) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.type != ConversationType.GROUP.value:
        raise ApiError(404, "NOT_FOUND", "群聊不存在")
    if active_only and conversation.state != ConversationState.ACTIVE.value:
        raise ApiError(409, "CONVERSATION_READ_ONLY", "群聊已解散，只读")
    return conversation


def check_group_version(conversation: Conversation, expected: int) -> None:
    if conversation.version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "群聊已更新，请刷新后重试", {"current_version": conversation.version})


def active_users_or_invalid(db: Session, user_ids: list[str]) -> list[User]:
    users = list(db.scalars(select(User).where(User.id.in_(user_ids), User.status == UserStatus.ACTIVE.value)))
    if len(users) != len(set(user_ids)):
        raise ApiError(422, "INVALID_MEMBERS", "成员必须均为启用用户")
    return users


def group_members(db: Session, conversation_id: str) -> list[tuple[ConversationMember, User]]:
    return list(db.execute(select(ConversationMember, User).join(User).where(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.state == MembershipState.ACTIVE.value,
    ).order_by(ConversationMember.joined_at, ConversationMember.id)).all())


@admin_router.get("/groups", response_model=SuccessResponse[dict])
def list_groups(request: Request, page: int = 1, page_size: int = 20, q: str | None = None, state: str | None = None,
                db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_manager(actor)
    if page < 1 or not 1 <= page_size <= 100 or state not in {None, "ACTIVE", "DISSOLVED"}:
        raise ApiError(422, "VALIDATION_ERROR", "查询参数不合法")
    statement = select(Conversation).where(Conversation.type == ConversationType.GROUP.value)
    if q and q.strip():
        statement = statement.where(Conversation.title.like(f"%{q.strip()}%"))
    if state:
        statement = statement.where(Conversation.state == state)
    groups = list(db.scalars(statement.order_by(Conversation.created_at.desc(), Conversation.id.desc())))
    return SuccessResponse(data={"items": [to_group(db, item).model_dump(mode="json") for item in groups[(page - 1) * page_size:page * page_size]], "page": page, "page_size": page_size, "total": len(groups)}, request_id=request_id(request))


@admin_router.post("/groups", status_code=201, response_model=SuccessResponse[GroupOut])
def create_group(payload: CreateGroupIn, request: Request, response: Response,
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[GroupOut]:
    require_csrf(request, db)
    require_manager(actor)
    serialized = payload.model_dump(mode="json")
    replay = idempotency_replay(db, actor, request, idempotency_key, serialized)
    if replay:
        response.status_code = replay.response_status
        response.headers["Idempotency-Replayed"] = "true"
        return SuccessResponse(data=GroupOut(**replay.response_data), request_id=request_id(request))
    requested_ids = [str(item) for item in payload.member_ids]
    # The creator is always a member, so the submitted set must contain another user.
    if actor.id in requested_ids:
        raise ApiError(422, "INVALID_MEMBERS", "创建者会自动加入，不应重复提交")
    active_users_or_invalid(db, requested_ids)
    conversation = Conversation(type=ConversationType.GROUP.value, title=payload.title, created_by=actor.id)
    db.add(conversation)
    db.flush()
    db.add_all([ConversationMember(conversation_id=conversation.id, user_id=user_id) for user_id in [actor.id, *requested_ids]])
    db.flush()
    audit_group(db, actor, conversation, "CHAT_GROUP_CREATED", member_count=1 + len(requested_ids))
    data = to_group(db, conversation).model_dump(mode="json")
    remember_idempotency(db, actor, request, idempotency_key or "", serialized, 201, data)
    db.commit()
    emit([actor.id, *requested_ids], "chat.membership.changed", {"conversation_id": conversation.id, "version": conversation.version})
    return SuccessResponse(data=GroupOut(**data), request_id=request_id(request))


@admin_router.patch("/groups/{conversation_id}", response_model=SuccessResponse[GroupOut])
def update_group(conversation_id: UUID, payload: UpdateGroupIn, request: Request,
                 db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[GroupOut]:
    require_csrf(request, db)
    require_manager(actor)
    conversation = group_or_404(db, str(conversation_id), active_only=True)
    check_group_version(conversation, payload.expected_version)
    conversation.title = payload.title
    conversation.version += 1
    audit_group(db, actor, conversation, "CHAT_GROUP_UPDATED")
    recipients = list(db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conversation.id, ConversationMember.state == MembershipState.ACTIVE.value)))
    db.commit()
    emit(recipients, "chat.membership.changed", {"conversation_id": conversation.id, "version": conversation.version})
    return SuccessResponse(data=to_group(db, conversation), request_id=request_id(request))


@admin_router.get("/groups/{conversation_id}/members", response_model=SuccessResponse[dict])
def admin_group_members(conversation_id: UUID, request: Request, page: int = 1, page_size: int = 20,
                        db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_manager(actor)
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError(422, "VALIDATION_ERROR", "分页参数不合法")
    rows = group_members(db, group_or_404(db, str(conversation_id)).id)
    return SuccessResponse(data={"items": [to_member(member, user).model_dump(mode="json") for member, user in rows[(page - 1) * page_size:page * page_size]], "page": page, "page_size": page_size, "total": len(rows)}, request_id=request_id(request))


@admin_router.post("/groups/{conversation_id}/members", response_model=SuccessResponse[dict])
def add_group_members(conversation_id: UUID, payload: AddMembersIn, request: Request, response: Response,
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    require_manager(actor)
    serialized = payload.model_dump(mode="json")
    replay = idempotency_replay(db, actor, request, idempotency_key, serialized)
    if replay:
        response.status_code = replay.response_status
        response.headers["Idempotency-Replayed"] = "true"
        return SuccessResponse(data=replay.response_data, request_id=request_id(request))
    conversation = group_or_404(db, str(conversation_id), active_only=True)
    check_group_version(conversation, payload.expected_version)
    user_ids = [str(item) for item in payload.user_ids]
    active_users_or_invalid(db, user_ids)
    existing = set(db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conversation.id, ConversationMember.state == MembershipState.ACTIVE.value)))
    if existing.intersection(user_ids) or len(existing) + len(user_ids) > 50:
        raise ApiError(409, "USER_UNAVAILABLE", "成员已在群内或人数超过上限")
    previous = list(db.scalars(select(ConversationMember).where(ConversationMember.conversation_id == conversation.id, ConversationMember.user_id.in_(user_ids))))
    previous_by_user = {member.user_id: member for member in previous}
    for user_id in user_ids:
        member = previous_by_user.get(user_id)
        if member is None:
            db.add(ConversationMember(conversation_id=conversation.id, user_id=user_id))
        else:
            # Re-invitation is an explicit management action; historical access
            # is intentionally restored, matching the group-history contract.
            member.state, member.removed_at = MembershipState.ACTIVE.value, None
    conversation.version += 1
    audit_group(db, actor, conversation, "CHAT_GROUP_MEMBERS_ADDED", member_count=len(user_ids))
    db.flush()
    rows = group_members(db, conversation.id)
    data = {"members": [to_member(member, user).model_dump(mode="json") for member, user in rows], "version": conversation.version}
    remember_idempotency(db, actor, request, idempotency_key or "", serialized, 200, data)
    recipients = [member.user_id for member, _ in rows]
    db.commit()
    emit(recipients, "chat.membership.changed", {"conversation_id": conversation.id, "version": conversation.version})
    return SuccessResponse(data=data, request_id=request_id(request))


@admin_router.delete("/groups/{conversation_id}/members/{user_id}", response_model=SuccessResponse[dict])
def remove_group_member(conversation_id: UUID, user_id: UUID, request: Request, if_match: str | None = Header(default=None),
                        db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[dict]:
    require_csrf(request, db)
    require_manager(actor)
    if not if_match or not if_match.startswith('"v') or not if_match.endswith('"') or not if_match[2:-1].isdigit():
        raise ApiError(428, "VERSION_REQUIRED", "移除成员需要 If-Match 版本")
    conversation = group_or_404(db, str(conversation_id), active_only=True)
    check_group_version(conversation, int(if_match[2:-1]))
    target = active_member_or_404(db, conversation.id, str(user_id))
    target.state, target.removed_at = MembershipState.REMOVED.value, now()
    conversation.version += 1
    audit_group(db, actor, conversation, "CHAT_GROUP_MEMBER_REMOVED", user_id=str(user_id))
    recipients = list(db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conversation.id, ConversationMember.state == MembershipState.ACTIVE.value)))
    db.commit()
    # Target is included so an existing client immediately clears local history.
    emit([*recipients, str(user_id)], "chat.membership.changed", {"conversation_id": conversation.id, "version": conversation.version})
    return SuccessResponse(data={"removed": True, "version": conversation.version}, request_id=request_id(request))


@admin_router.post("/groups/{conversation_id}/dissolve", response_model=SuccessResponse[GroupOut])
def dissolve_group(conversation_id: UUID, payload: DissolveGroupIn, request: Request,
                   db: Session = Depends(get_db), actor: User = Depends(require_user)) -> SuccessResponse[GroupOut]:
    require_csrf(request, db)
    require_manager(actor)
    conversation = group_or_404(db, str(conversation_id), active_only=True)
    check_group_version(conversation, payload.expected_version)
    conversation.state, conversation.dissolved_at = ConversationState.DISSOLVED.value, now()
    conversation.version += 1
    audit_group(db, actor, conversation, "CHAT_GROUP_DISSOLVED")
    recipients = list(db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conversation.id, ConversationMember.state == MembershipState.ACTIVE.value)))
    db.commit()
    emit(recipients, "chat.conversation.dissolved", {"conversation_id": conversation.id, "version": conversation.version})
    return SuccessResponse(data=to_group(db, conversation), request_id=request_id(request))
