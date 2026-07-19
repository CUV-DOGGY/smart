import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


# ==================== 启动时初始化 ====================
async def startup_db():
    """连接 MongoDB"""
    from app.config import settings
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    return client, db


async def startup_redis():
    """连接 Redis"""
    import redis.asyncio as redis
    from app.config import settings
    client = redis.from_url(settings.REDIS_URL)
    return client


def create_llm():
    """创建 LLM 实例"""
    # 从 models.llm 获取已创建的 LLM
    from app.models.llm import create_llm as _create_llm
    return _create_llm()


# ==================== 关闭时清理 ====================
async def shutdown_db(client):
    """断开 MongoDB"""
    if client:
        client.close()


async def shutdown_redis(redis_client):
    """断开 Redis"""
    if redis_client:
        await redis_client.close()


# ==================== Lifespan ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 30)
    logger.info("应用启动中...")

    # 1. 连接 MongoDB
    logger.info("连接 MongoDB...")
    mongo_client, db = await startup_db()
    app.state.mongo_client = mongo_client
    app.state.db = db
    logger.info("MongoDB 连接成功")

    # 2. 连接 Redis
    # logger.info("连接 Redis...")
    # redis_client = await startup_redis()
    # app.state.redis = redis_client
    # logger.info("Redis 连接成功")

    # 3. 创建 LLM
    logger.info("初始化 LLM...")
    llm = create_llm()
    app.state.llm = llm
    logger.info("LLM 初始化成功")

    logger.info("应用启动完成")
    logger.info("=" * 30)

    yield

    logger.info("=" * 30)
    logger.info("应用关闭中...")

    # 关闭时断开连接
    await shutdown_db(app.state.mongo_client)
    # await shutdown_redis(app.state.redis)

    logger.info("应用已关闭")
    logger.info("=" * 30)
