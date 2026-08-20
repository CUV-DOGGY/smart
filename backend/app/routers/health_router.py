import asyncio
import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["系统健康"])
READINESS_TIMEOUT_SECONDS = 2.0


async def _check_component(
    name: str,
    operation: Callable[[], Awaitable[object]],
) -> str:
    try:
        await asyncio.wait_for(operation(), timeout=READINESS_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("%s readiness check failed", name, exc_info=True)
        return "unavailable"
    return "ok"


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request) -> JSONResponse:
    async def ping_mongodb() -> None:
        database = request.app.state.db
        await database.command("ping")

    async def ping_redis() -> None:
        redis_client = request.app.state.redis
        await redis_client.ping()

    mongodb_status, redis_status = await asyncio.gather(
        _check_component("mongodb", ping_mongodb),
        _check_component("redis", ping_redis),
    )
    components = {
        "mongodb": mongodb_status,
        "redis": redis_status,
    }
    is_ready = all(status == "ok" for status in components.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "status": "ready" if is_ready else "not_ready",
            "components": components,
        },
    )
