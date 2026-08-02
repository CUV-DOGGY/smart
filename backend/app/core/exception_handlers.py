import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pymongo.errors import ConnectionFailure, ExecutionTimeout

from app.core.database_errors import DatabaseUnavailableError


logger = logging.getLogger(__name__)


async def handle_database_unavailable(
    request: Request,
    exc: DatabaseUnavailableError | ConnectionFailure | ExecutionTimeout,
) -> JSONResponse:
    logger.exception(
        "MongoDB unavailable while handling %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": {
                "code": "DATABASE_UNAVAILABLE",
                "message": "数据库暂时不可用，请稍后重试",
            }
        },
        headers={"Retry-After": "1"},
    )


def setup_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        DatabaseUnavailableError,
        handle_database_unavailable,
    )
    # 兜底处理尚未在 Repository 边界转换的 MongoDB 可用性异常。
    app.add_exception_handler(
        ConnectionFailure,
        handle_database_unavailable,
    )
    app.add_exception_handler(
        ExecutionTimeout,
        handle_database_unavailable,
    )
