import re
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.observability.context import (
    bind_request_id,
    reset_request_id,
    set_current_span_request_id,
)


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
CORS_ALLOWED_HEADERS = [
    "Authorization",
    "Content-Type",
    "Idempotency-Key",
    "X-Request-ID",
    "traceparent",
    "tracestate",
    "baggage",
]


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        submitted = headers.get(b"x-request-id", b"").decode(
            "ascii",
            errors="ignore",
        )
        request_id = (
            submitted
            if REQUEST_ID_PATTERN.fullmatch(submitted)
            else str(uuid.uuid4())
        )
        scope.setdefault("state", {})["request_id"] = request_id
        request_id_token = bind_request_id(request_id)
        set_current_span_request_id(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append(
                    (b"x-request-id", request_id.encode("ascii"))
                )
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            reset_request_id(request_id_token)


class AuthRequestBodyLimitMiddleware:
    """对认证路由同时校验 Content-Length 和实际流式请求体大小。"""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(
            "/auth/"
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_body_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return

        # 认证请求体上限很小，先读取并校验后再回放给 FastAPI。
        # 这样即使客户端使用 chunked encoding，也不会让超大数据进入表单解析器。
        buffered_messages: list[Message] = []
        received_bytes = 0
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    await self._reject(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                return

        message_index = 0

        async def replay_receive() -> Message:
            nonlocal message_index
            if message_index < len(buffered_messages):
                message = buffered_messages[message_index]
                message_index += 1
                return message
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": "请求体过大"},
        )
        await response(scope, receive, send)


# ==================== Middleware ====================
def setup_middleware(app: FastAPI) -> None:
    """配置中间件"""
    app.add_middleware(
        AuthRequestBodyLimitMiddleware,
        max_body_bytes=settings.AUTH_MAX_REQUEST_BODY_BYTES,
    )
    app.add_middleware(RequestIdMiddleware)

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials="*" not in settings.CORS_ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=CORS_ALLOWED_HEADERS,
        expose_headers=["X-Request-ID", "Retry-After"],
    )
