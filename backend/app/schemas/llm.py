"""Strict request and response schemas for the cloud text assistant."""

from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from app.schemas.auth import StrictModel


ProviderName = Literal["DEEPSEEK", "QWEN"]
AssistantMode = Literal["GENERAL", "KNOWLEDGE", "SUMMARY", "REPORT"]


class ProviderConfigCreate(StrictModel):
    provider: ProviderName
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=8, max_length=300)
    model: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=1, max_length=512)
    enabled: bool = False
    max_output_tokens: int = Field(default=2048, ge=256, le=4096)
    temperature: float = Field(default=0.7, ge=0, le=2)
    timeout_seconds: Literal[60] = 60
    daily_request_limit: int = Field(default=100, ge=1, le=1000)


class ProviderConfigPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=8, max_length=300)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    api_key: str | None = Field(default=None, min_length=1, max_length=512)
    enabled: bool | None = None
    max_output_tokens: int | None = Field(default=None, ge=256, le=4096)
    temperature: float | None = Field(default=None, ge=0, le=2)
    daily_request_limit: int | None = Field(default=None, ge=1, le=1000)
    expected_version: int = Field(ge=1)


class ProviderConfigOut(StrictModel):
    capabilities: dict | None = None
    id: str
    provider: ProviderName
    name: str
    base_url: str
    model: str
    enabled: bool
    has_api_key: bool
    api_key_masked: str
    max_output_tokens: int
    temperature: float
    timeout_seconds: int
    daily_request_limit: int
    is_validated: bool
    validated_at: datetime | None
    version: int


class ProviderTestIn(StrictModel):
    consent_to_test: Literal[True]
    expected_version: int = Field(ge=1)
    test_stream: bool = False
    temperature_min: float | None = Field(default=0.7, ge=0, le=2)
    temperature_max: float | None = Field(default=0.7, ge=0, le=2)

    @model_validator(mode="after")
    def valid_test_range(self):
        if (self.temperature_min is None) != (self.temperature_max is None):
            raise ValueError("不发送温度参数时，上下限须同时为空")
        if self.temperature_min is not None and self.temperature_min > self.temperature_max:
            raise ValueError("温度下限不能超过上限")
        return self


class LlmSettingsIn(StrictModel):
    default_provider_config_id: str = Field(min_length=36, max_length=36)
    expected_version: int = Field(ge=1)


class KnowledgeCreate(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=10000)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"


class KnowledgePatch(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def has_change(self) -> "KnowledgePatch":
        if self.title is None and self.content is None and self.status is None:
            raise ValueError("至少提供一个要修改的字段")
        return self


class KnowledgeOut(StrictModel):
    id: str
    title: str
    content: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class AssistantConversationCreate(StrictModel):
    title: str = Field(default="", max_length=100)


class PrepareRequestIn(StrictModel):
    conversation_id: str = Field(min_length=36, max_length=36)
    mode: AssistantMode
    question: str = Field(min_length=1, max_length=4000)
    detection_ids: list[str] = Field(default_factory=list, max_length=10)
    agent_profile_id: str = Field(min_length=36, max_length=36)

    @model_validator(mode="after")
    def validate_sources(self) -> "PrepareRequestIn":
        if self.mode in {"SUMMARY", "REPORT"} and not self.detection_ids:
            raise ValueError("摘要和报告必须选择检测记录")
        if self.mode not in {"SUMMARY", "REPORT"} and self.detection_ids:
            raise ValueError("该模式不能选择检测记录")
        if len(set(self.detection_ids)) != len(self.detection_ids):
            raise ValueError("检测记录不能重复")
        return self


class ConfirmRequestIn(StrictModel):
    payload_hash: str = Field(min_length=64, max_length=64)
    consent: Literal[True]
