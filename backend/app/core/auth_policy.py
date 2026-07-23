USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 50
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PASSWORD_MAX_BYTES = 512


def normalize_username(username: str) -> str:
    """为注册、登录、数据库查询和限流生成同一个用户名。"""
    # 保留项目原有 lower() 存储规则，避免已有用户名需要数据迁移。
    return username.strip().lower()


def is_valid_normalized_username(username: str) -> bool:
    """校验归一化后的用户名，避免空白和超长输入进入数据库。"""
    return USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH


def is_valid_password_size(password: str) -> bool:
    """同时约束字符数和 UTF-8 字节数，防止超大输入进入 Argon2。"""
    return (
        PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH
        and len(password.encode("utf-8")) <= PASSWORD_MAX_BYTES
    )
