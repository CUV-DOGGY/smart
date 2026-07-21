import uuid
from datetime import datetime, timezone

from app.core.security import create_access_token, hash_password, verify_password
from app.repositories.auth_repository import AuthRepository, UsernameConflictError
from app.schemas.auth import RegisterRequest, RegisterResponse, TokenResponse


class UsernameAlreadyExistsError(RuntimeError):
    """注册时用户名已存在。"""


class AuthenticationError(RuntimeError):
    """用户名、密码或用户状态不允许登录。"""


class AuthService:
    def __init__(self, repository: AuthRepository):
        self.repository = repository

    async def register(self, request: RegisterRequest) -> RegisterResponse:
        username = request.username.strip().lower()
        existing_user = await self.repository.find_by_username(username)
        if existing_user is not None:
            raise UsernameAlreadyExistsError("用户名已经存在")

        user_id = str(uuid.uuid4())
        user_data = {
            "user_id": user_id,
            "username": username,
            "password_hash": hash_password(request.password),
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
        normalized_username = username.strip().lower()
        user = await self.repository.find_by_username(normalized_username)

        # 不区分“用户名不存在”和“密码错误”，避免泄露已注册用户名。
        if user is None:
            raise AuthenticationError("用户名或密码错误")

        if not verify_password(password, user["password_hash"]):
            raise AuthenticationError("用户名或密码错误")

        if user.get("disabled", False):
            raise AuthenticationError("用户已经被禁用")

        return TokenResponse(
            access_token=create_access_token(user["user_id"]),
            token_type="bearer",
        )
