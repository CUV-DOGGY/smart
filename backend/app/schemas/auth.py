from pydantic import BaseModel, Field, field_validator

from app.core.auth_policy import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    is_valid_normalized_username,
    is_valid_password_size,
    normalize_username,
)


class RegisterRequest(BaseModel):
    username: str = Field(
        min_length=USERNAME_MIN_LENGTH,
        max_length=USERNAME_MAX_LENGTH,
    )
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )

    @field_validator("username")
    @classmethod
    def normalize_submitted_username(cls, value: str) -> str:
        normalized = normalize_username(value)
        if not is_valid_normalized_username(normalized):
            raise ValueError("用户名归一化后长度不合法")
        return normalized

    @field_validator("password")
    @classmethod
    def reject_oversized_password(cls, value: str) -> str:
        if not is_valid_password_size(value):
            raise ValueError("密码超过允许的字节长度")
        return value


class RegisterResponse(BaseModel):
    user_id: str
    username: str
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthenticatedUser(BaseModel):
    user_id: str
    username: str
