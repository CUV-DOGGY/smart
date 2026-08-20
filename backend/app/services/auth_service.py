import uuid
from datetime import datetime, timezone

from app.core.auth_policy import (
    is_valid_normalized_username,
    is_valid_password_size,
    normalize_username,
)
from app.core.security import (
    create_access_token,
    get_dummy_password_hash,
    hash_password,
    verify_password,
)
from app.ports.errors import UsernameConflictError
from app.ports.repositories import AuthRepositoryPort
from app.schemas.auth import (
    AuthenticatedUser,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)


class UsernameAlreadyExistsError(RuntimeError):
    """注册时用户名已存在。"""


class AuthenticationError(RuntimeError):
    """用户名、密码或用户状态不允许登录。"""


INVALID_PASSWORD_PLACEHOLDER = "invalid-login-input-for-dummy-hash"


class AuthService:
    def __init__(self, repository: AuthRepositoryPort):
        self.repository = repository

    async def authenticated_user(self, user_id: str) -> AuthenticatedUser | None:
        user = await self.repository.find_by_user_id(user_id)
        if user is None or user.get("disabled", False):
            return None
        return AuthenticatedUser(
            user_id=user["user_id"],
            username=user["username"],
        )

    async def register(self, request: RegisterRequest) -> RegisterResponse:
        username = normalize_username(request.username)
        existing_user = await self.repository.find_by_username(username)
        if existing_user is not None:
            raise UsernameAlreadyExistsError("用户名已经存在")

        user_id = str(uuid.uuid4())
        user_data = {
            "user_id": user_id,
            "username": username,
            "password_hash": await hash_password(request.password),
            "disabled": False,
            "create_time": datetime.now(timezone.utc),
        }

        try:
            await self.repository.create_user(user_data)
        except UsernameConflictError as exc:
            # 唯一索引负责拦截两个并发注册请求。
            raise UsernameAlreadyExistsError("用户名已经存在") from exc

        return RegisterResponse(
            user_id=user_id,
            username=username,
            message="注册成功",
        )

    async def login(self, username: str, password: str) -> TokenResponse:
        normalized_username = normalize_username(username)
        username_is_valid = is_valid_normalized_username(normalized_username)
        password_is_valid = is_valid_password_size(password)

        # 非法或超长用户名不进入数据库，但仍然执行一次假 Argon2。
        user = (
            await self.repository.find_by_username(normalized_username)
            if username_is_valid
            else None
        )

        # 用户不存在时也验证固定假哈希，降低响应时间差造成的用户名枚举。
        stored_password_hash = (
            user["password_hash"]
            if user is not None and password_is_valid
            else get_dummy_password_hash()
        )
        password_candidate = (
            password if password_is_valid else INVALID_PASSWORD_PLACEHOLDER
        )
        password_matched = await verify_password(
            password_candidate,
            stored_password_hash,
        )

        if user is None or not password_is_valid or not password_matched:
            raise AuthenticationError("用户名或密码错误")

        if user.get("disabled", False):
            raise AuthenticationError("用户已经被禁用")

        return TokenResponse(
            access_token=create_access_token(user["user_id"]),
            token_type="bearer",
        )
