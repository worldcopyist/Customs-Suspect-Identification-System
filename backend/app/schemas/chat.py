"""Strict request and response structures for internal communication."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.auth import StrictModel


class UserDirectoryOut(StrictModel):
    id: str
    username: str
    display_name: str


class ConversationOut(StrictModel):
    id: str
    type: Literal["DIRECT", "GROUP", "PUBLIC"]
    title: str
    state: Literal["ACTIVE", "DISSOLVED"]
    member_count: int
    last_seq: str
    last_read_seq: str
    unread_count: int
    version: int


class GroupOut(StrictModel):
    id: str
    title: str
    type: Literal["GROUP"] = "GROUP"
    state: Literal["ACTIVE", "DISSOLVED"]
    member_count: int
    created_by: str | None
    version: int
    created_at: datetime
    dissolved_at: datetime | None


class MemberOut(UserDirectoryOut):
    state: Literal["ACTIVE", "REMOVED"]
    joined_at: datetime
    removed_at: datetime | None


class MessageOut(StrictModel):
    message_type: Literal["TEXT"] = "TEXT"
    id: str
    conversation_id: str
    sender_id: str | None
    sender_display_name: str
    seq: str
    client_message_id: str
    content: str
    created_at: datetime


class MessagePageOut(StrictModel):
    items: list[MessageOut]
    has_more: bool
    next_after_seq: str | None
    next_before_seq: str | None


class DirectConversationIn(StrictModel):
    peer_user_id: UUID


class SendMessageIn(StrictModel):
    client_message_id: UUID
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def non_blank_content(cls, value: str) -> str:
        if not value:
            raise ValueError("消息内容不能为空")
        return value


class ReadConversationIn(StrictModel):
    last_read_seq: str = Field(pattern=r"^(0|[1-9][0-9]*)$")


class CreateGroupIn(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    member_ids: list[UUID] = Field(min_length=1, max_length=49)

    @field_validator("member_ids")
    @classmethod
    def distinct_members(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("成员不能重复")
        return value


class UpdateGroupIn(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


class AddMembersIn(StrictModel):
    user_ids: list[UUID] = Field(min_length=1, max_length=20)
    expected_version: int = Field(ge=1)

    @field_validator("user_ids")
    @classmethod
    def distinct_members(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("成员不能重复")
        return value


class DissolveGroupIn(StrictModel):
    expected_version: int = Field(ge=1)
