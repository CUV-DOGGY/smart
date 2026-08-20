from app.core import (
    Logger,
    lifespan,
    setup_exception_handlers,
    setup_middleware,
)
from app.schemas.chat import ChatRequest, ChatResponse
from app.dependencies.auth import get_current_user_id
from app.routers.address_router import router as address_router
from app.routers.auth_router import router as auth_router
from app.routers.health_router import router as health_router
from app.routers.order_router import router as order_router
import logging
from typing import Annotated
from fastapi import Depends, FastAPI

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


# ==================== Routes ====================
@app.post("/chat", response_model=ChatResponse, tags=["外卖智能客服"])
async def chat(
    request: ChatRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    """智能客服聊天接口"""
    pass
