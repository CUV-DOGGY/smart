from app.core import (
    Logger,
    lifespan,
    setup_exception_handlers,
    setup_middleware,
)
from app.routers.address_router import router as address_router
from app.routers.auth_router import router as auth_router
from app.routers.catalog_router import router as catalog_router
from app.routers.chat_router import chat_router, conversation_router
from app.routers.health_router import router as health_router
from app.routers.order_router import router as order_router
from app.routers.telemetry_router import router as telemetry_router
from app.observability import setup_observability
import logging
from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ==================== App ====================
app = FastAPI(
    title="智能客服 API",
    version="1.0.0",
    lifespan=lifespan,
)

setup_exception_handlers(app)
setup_middleware(app)
app.include_router(auth_router)
app.include_router(address_router)
app.include_router(order_router)
app.include_router(health_router)
app.include_router(catalog_router)
app.include_router(chat_router)
app.include_router(conversation_router)
app.include_router(telemetry_router)

# Instrument the fully assembled ASGI application before lifespan creates
# MongoDB, Redis, HTTPX and LLM clients.
setup_observability(app)
