from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import Role, UserStatus


USERNAME_PATTERN = r"^[a-zA-Z0-9_]{3,32}$"
PASSWORD_MIN_LENGTH = 12
DEFAULT_PERMISSIONS = {
    "person.read",
    "detection.camera",
    "detection.image",
    "detection.read",
    "detection.review",
    "chat.use",
    "assistant.use",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UserOut(StrictModel):
    id: str
    username: str
    display_name: str
    role: Role
    status: UserStatus
    is_builtin: bool
    must_change_password: bool
    permissions: list[str]
    version: int
    created_at: datetime
    updated_at: datetime


class CsrfOut(StrictModel):
    csrf_token: str
    expires_at: datetime


class RegisterIn(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    username: str = Field(pattern=USERNAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)
    password_confirm: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)

    @model_validator(mode="after")
    def passwords_match_and_are_safe(self) -> "RegisterIn":
        if self.password != self.password_confirm:
            raise ValueError("两次密码输入不一致")
        validate_password(self.password, self.username)
        return self


class LoginIn(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    portal: Literal["CLIENT", "ADMIN"] = "CLIENT"
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class LoginOut(StrictModel):
    user: UserOut
    session_phase: Literal["FULL", "CHANGE_PASSWORD"]
    csrf_token: str
    expires_at: datetime
    auth_scheme: Literal["JWT_COOKIE"]
    session_id: str
    idle_timeout_seconds: Literal[1800]


class UpdateMeIn(StrictModel):
    display_name: str = Field(min_length=1, max_length=50)
    expected_version: int = Field(ge=1)


class ChangePasswordIn(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)
    new_password_confirm: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)

    @model_validator(mode="after")
    def new_passwords_match(self) -> "ChangePasswordIn":
        if self.new_password != self.new_password_confirm:
            raise ValueError("两次新密码输入不一致")
        return self


class CreateUserIn(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    username: str = Field(pattern=USERNAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=50)
    temporary_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)

    @field_validator("username")
    @classmethod
    def normalized_username(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def valid_password(self) -> "CreateUserIn":
        validate_password(self.temporary_password, self.username)
        return self


class UpdateUserIn(StrictModel):
    display_name: str = Field(min_length=1, max_length=50)
    expected_version: int = Field(ge=1)


class StatusIn(StrictModel):
    status: Literal["ACTIVE", "DISABLED"]
    expected_version: int = Field(ge=1)


class RoleIn(StrictModel):
    role: Literal["ADMIN", "USER"]
    expected_version: int = Field(ge=1)


class PermissionsIn(StrictModel):
    permissions: list[str]
    expected_version: int = Field(ge=1)

    @field_validator("permissions")
    @classmethod
    def permitted_set(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(item not in DEFAULT_PERMISSIONS for item in value):
            raise ValueError("权限集合不合法")
        if "detection.review" in value and "detection.read" not in value:
            raise ValueError("复核权限必须同时拥有记录查看权限")
        return sorted(value)


class ResetPasswordIn(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    temporary_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)
    expected_version: int = Field(ge=1)


def validate_password(password: str, username: str) -> None:
    if password == "admin123" or password.lower() == username.lower():
        raise ValueError("密码不能使用保留弱口令或用户名")
