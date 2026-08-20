import logging
import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymongo.errors import ConnectionFailure, ExecutionTimeout

from app.core.api_errors import ApiError
from app.core.database_errors import DatabaseUnavailableError


logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id is None:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
    return request_id


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    field_errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "field_errors": field_errors or [],
            "request_id": _request_id(request),
        },
        headers=headers,
    )


async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return _error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        field_errors=exc.field_errors,
        headers=exc.headers,
    )


async def handle_http_exception(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code", f"HTTP_{exc.status_code}"))
        message = str(detail.get("message", "请求失败"))
    else:
        code = f"HTTP_{exc.status_code}"
        message = str(detail)
    return _error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        headers=exc.headers,
    )


async def handle_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    field_errors = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", [])]
        if location and location[0] in {"body", "query", "path", "header"}:
            location = location[1:]
        field_errors.append(
            {
                "field": ".".join(location),
                "message": str(error.get("msg", "字段格式不正确")),
            }
        )
    return _error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="VALIDATION_ERROR",
        message="请求参数校验失败",
        field_errors=field_errors,
    )


async def handle_database_unavailable(
    request: Request,
    exc: DatabaseUnavailableError | ConnectionFailure | ExecutionTimeout,
) -> JSONResponse:
    logger.exception(
        "MongoDB unavailable while handling %s %s request_id=%s",
        request.method,
        request.url.path,
        _request_id(request),
    )
    return _error_response(
        request,
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="DATABASE_UNAVAILABLE",
        message="数据库暂时不可用，请稍后重试",
        headers={"Retry-After": "1"},
    )


async def handle_unexpected_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "Unhandled error while handling %s %s request_id=%s",
        request.method,
        request.url.path,
        _request_id(request),
    )
    return _error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_ERROR",
        message="服务暂时不可用，请稍后重试",
    )


def setup_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(DatabaseUnavailableError, handle_database_unavailable)
    app.add_exception_handler(ConnectionFailure, handle_database_unavailable)
    app.add_exception_handler(ExecutionTimeout, handle_database_unavailable)
    app.add_exception_handler(Exception, handle_unexpected_error)
