from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from app.config import settings
from app.core.api_errors import ApiError
from app.dependencies.auth import get_current_user_id
from app.dependencies.cache import get_redis
from app.services.telemetry_rate_limiter import (
    TelemetryRateLimitBackendError,
    TelemetryRateLimitExceeded,
    TelemetryRateLimiter,
)


router = APIRouter(prefix="/telemetry", tags=["telemetry"])
ALLOWED_CONTENT_TYPES = {"application/json", "application/x-protobuf"}


def get_telemetry_rate_limiter(redis=Depends(get_redis)) -> TelemetryRateLimiter:
    return TelemetryRateLimiter(redis)


@router.post("/v1/traces", status_code=204, include_in_schema=False)
async def ingest_browser_traces(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    rate_limiter: Annotated[
        TelemetryRateLimiter,
        Depends(get_telemetry_rate_limiter),
    ],
) -> Response:
    if not settings.BROWSER_TELEMETRY_ENABLED:
        raise ApiError(404, "TELEMETRY_DISABLED", "浏览器遥测入口未启用")

    origin = request.headers.get("origin")
    if origin not in settings.BROWSER_TELEMETRY_ALLOWED_ORIGINS:
        raise ApiError(403, "TELEMETRY_ORIGIN_DENIED", "遥测来源不受信任")

    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type.lower() not in ALLOWED_CONTENT_TYPES:
        raise ApiError(
            415,
            "TELEMETRY_CONTENT_TYPE_UNSUPPORTED",
            "遥测数据格式不受支持",
        )
    content_encoding = request.headers.get("content-encoding", "").lower()
    if content_encoding not in {"", "gzip"}:
        raise ApiError(
            415,
            "TELEMETRY_CONTENT_ENCODING_UNSUPPORTED",
            "遥测压缩格式不受支持",
        )

    try:
        await rate_limiter.check(user_id)
    except TelemetryRateLimitExceeded as exc:
        raise ApiError(
            429,
            "TELEMETRY_RATE_LIMITED",
            "遥测上报过于频繁",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except TelemetryRateLimitBackendError as exc:
        raise ApiError(
            503,
            "TELEMETRY_RATE_LIMIT_UNAVAILABLE",
            "遥测入口暂时不可用",
        ) from exc

    payload = await _read_bounded_body(request)
    if not payload:
        raise ApiError(400, "TELEMETRY_PAYLOAD_EMPTY", "遥测数据不能为空")

    try:
        await _forward_traces(
            payload,
            content_type=content_type,
            content_encoding=content_encoding,
        )
    except httpx.HTTPError as exc:
        raise ApiError(
            503,
            "TELEMETRY_COLLECTOR_UNAVAILABLE",
            "遥测接收端暂时不可用",
        ) from exc
    return Response(status_code=204)


async def _read_bounded_body(request: Request) -> bytes:
    limit = settings.BROWSER_TELEMETRY_MAX_REQUEST_BODY_BYTES
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise ApiError(
                    413,
                    "TELEMETRY_PAYLOAD_TOO_LARGE",
                    "遥测数据过大",
                )
        except ValueError as exc:
            raise ApiError(
                400,
                "TELEMETRY_CONTENT_LENGTH_INVALID",
                "Content-Length 无效",
            ) from exc

    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise ApiError(
                413,
                "TELEMETRY_PAYLOAD_TOO_LARGE",
                "遥测数据过大",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _forward_traces(
    payload: bytes,
    *,
    content_type: str,
    content_encoding: str,
) -> None:
    endpoint = f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT.rstrip('/')}/v1/traces"
    headers = {"Content-Type": content_type}
    if content_encoding:
        headers["Content-Encoding"] = content_encoding
    async with httpx.AsyncClient(
        timeout=settings.BROWSER_TELEMETRY_FORWARD_TIMEOUT_SECONDS,
    ) as client:
        response = await client.post(endpoint, content=payload, headers=headers)
        response.raise_for_status()
