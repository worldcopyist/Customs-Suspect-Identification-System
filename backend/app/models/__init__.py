"""认证与账户相关 SQLAlchemy 实体。"""

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Role(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    USER = "USER"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DELETED = "DELETED"


class SessionPhase(StrEnum):
    ANONYMOUS = "ANONYMOUS"
    CHANGE_PASSWORD = "CHANGE_PASSWORD"
    FULL = "FULL"


class ConversationType(StrEnum):
    PUBLIC = "PUBLIC"
    DIRECT = "DIRECT"
    GROUP = "GROUP"


class ConversationState(StrEnum):
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"


class MembershipState(StrEnum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=Role.USER.value)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=UserStatus.ACTIVE.value)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    phase: Mapped[str] = mapped_column(String(24), nullable=False, default=SessionPhase.ANONYMOUS.value)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    presence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user: Mapped[User | None] = relationship(back_populates="sessions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    target_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Media(Base):
    """A normalized, server-owned image used by detection tasks."""

    __tablename__ = "media"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    upload_byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="STAGED")
    storage_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="QUEUED", index=True)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="NOT_APPLICABLE")
    model_id: Mapped[str | None] = mapped_column(String(64))
    model_sha256: Mapped[str | None] = mapped_column(String(64))
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_media_id: Mapped[str | None] = mapped_column(ForeignKey("media.id", ondelete="RESTRICT"), index=True)
    rendered_media_id: Mapped[str | None] = mapped_column(ForeignKey("media.id"))
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("detection_batches.id"), index=True)
    batch_index: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warning_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    image_width: Mapped[int | None] = mapped_column(Integer)
    image_height: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boxes: Mapped[list["DetectionBox"]] = relationship(
        back_populates="detection", cascade="all, delete-orphan", order_by="DetectionBox.box_index"
    )


class DetectionBox(Base):
    __tablename__ = "detection_boxes"
    __table_args__ = (UniqueConstraint("detection_id", "box_index", name="uq_detection_box_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    detection_id: Mapped[str] = mapped_column(ForeignKey("detections.id", ondelete="CASCADE"), nullable=False, index=True)
    box_index: Mapped[int] = mapped_column(Integer, nullable=False)
    class_id: Mapped[int] = mapped_column(Integer, nullable=False)
    class_name: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    person_link: Mapped[dict | None] = mapped_column(JSON)
    detection: Mapped[Detection] = relationship(back_populates="boxes")


class CameraSession(Base):
    __tablename__ = "camera_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", index=True)
    client_label: Mapped[str | None] = mapped_column(String(100))
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    capture_interval_ms: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    type: Mapped[str] = mapped_column(String(12), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(12), nullable=False, default=ConversationState.ACTIVE.value)
    # Server-generated, lexically ordered pair prevents duplicate private chats.
    direct_key: Mapped[str | None] = mapped_column(String(73), unique=True, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dissolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConversationMember(Base):
    __tablename__ = "conversation_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_conversation_members_pair"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False)
    state: Mapped[str] = mapped_column(String(12), nullable=False, default=MembershipState.ACTIVE.value)
    last_read_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_chat_messages_sequence"),
        UniqueConstraint("conversation_id", "client_message_id", name="uq_chat_messages_client_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False)
    sender_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    sender_display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_message_id: Mapped[str] = mapped_column(String(36), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("user_id", "method", "path", "key", name="uq_idempotency_scope"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    key: Mapped[str] = mapped_column(String(36), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProviderConfig(Base):
    """A server-owned cloud text provider configuration.

    The API key is encrypted at rest and is deliberately absent from every
    response model and audit record.
    """

    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(16), nullable=False)  # DEEPSEEK / QWEN
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(300), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    daily_request_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    validation_fingerprint: Mapped[str | None] = mapped_column(String(64))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capabilities: Mapped[dict | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class LlmSettings(Base):
    __tablename__ = "llm_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    default_provider_config_id: Mapped[str | None] = mapped_column(ForeignKey("provider_configs.id", ondelete="SET NULL"))
    default_agent_profile_id: Mapped[str | None] = mapped_column(ForeignKey("agent_profiles.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ProviderCallLedger(Base):
    """A redacted accounting event; it contains neither payload nor secret."""

    __tablename__ = "provider_call_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_config_id: Mapped[str] = mapped_column(ForeignKey("provider_configs.id", ondelete="RESTRICT"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # TEST only; sends are AssistantRequest rows
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "document_version", "chunk_index", name="uq_knowledge_chunk_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    terms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class AssistantConversation(Base):
    __tablename__ = "assistant_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    context_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AssistantRequest(Base):
    __tablename__ = "assistant_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="RESTRICT"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PREPARED", index=True)
    provider_config_id: Mapped[str] = mapped_column(ForeignKey("provider_configs.id", ondelete="RESTRICT"), nullable=False)
    provider_version: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_profile_id: Mapped[str | None] = mapped_column(ForeignKey("agent_profiles.id"))
    agent_version: Mapped[int | None] = mapped_column(Integer)
    agent_name_snapshot: Mapped[str | None] = mapped_column(String(100))
    prompt_template_version: Mapped[str] = mapped_column(String(64), default="customs-text-v2", nullable=False)
    delivery_mode: Mapped[str] = mapped_column(String(32), default="BUFFERED_FINAL", nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outbound_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_refs: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    conversation_context_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    warning_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    usage: Mapped[dict | None] = mapped_column(JSON)
    billing_state: Mapped[str] = mapped_column(String(16), nullable=False, default="NOT_SENT")
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64))
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_id: Mapped[str] = mapped_column(ForeignKey("assistant_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    source_refs: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
