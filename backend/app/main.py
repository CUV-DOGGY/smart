from app.core import Logger, setup_middleware, lifespan
from app.routers import smarttalk
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
app.include_router(smarttalk.router)
