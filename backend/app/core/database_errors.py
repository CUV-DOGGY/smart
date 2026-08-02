from pymongo.errors import ConnectionFailure, ExecutionTimeout


class DatabaseUnavailableError(RuntimeError):
    """MongoDB 当前无法完成请求。"""


MONGO_UNAVAILABLE_EXCEPTIONS = (
    ConnectionFailure,
    ExecutionTimeout,
)
