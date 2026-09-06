"""V1.2 durable entities; no demo records are seeded."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class Person(Base):
    __tablename__ = "persons"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    person_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    attention_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    photo_media_id: Mapped[str | None] = mapped_column(ForeignKey("media.id"))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class DetectionBatch(Base):
    __tablename__ = "detection_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), default="RUNNING", nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    counts: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class DetectionHistory(Base):
    __tablename__ = "detection_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    detection_id: Mapped[str] = mapped_column(ForeignKey("detections.id"), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    before: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    after: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AgentProfile(Base):
    __tablename__ = "agent_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    business_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[float | None] = mapped_column(Float)
    provider_config_id: Mapped[str] = mapped_column(ForeignKey("provider_configs.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="INACTIVE", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class OperationLog(Base):
    __tablename__ = "operation_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    event_code: Mapped[str] = mapped_column(String(80), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(36))
    safe_context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
