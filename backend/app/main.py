from app.core import Logger, setup_middleware, lifespan
from app.schemas.chat import ChatRequest, ChatResponse
from app.routers.order_router import router as order_router
import logging
from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ==================== App ====================
app = FastAPI(
    title="智能客服 API",
    version="1.0.0",
    lifespan=lifespan,
)

setup_middleware(app)
app.include_router(order_router)


# ==================== Routes ====================
@app.post("/chat", response_model=ChatResponse, tags=["外卖智能客服"])
async def chat(request: ChatRequest):
    """智能客服聊天接口"""
    pass