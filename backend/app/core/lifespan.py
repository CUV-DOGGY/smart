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
    client = redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        health_check_interval=settings.REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
    )
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        raise
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
        await redis_client.aclose()


# ==================== Lifespan ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 30)
    logger.info("应用启动中...")
    mongo_client = None
    redis_client = None

    try:
        # 1. 连接 MongoDB
        logger.info("连接 MongoDB...")
        mongo_client, db = await startup_db()
        app.state.mongo_client = mongo_client
        app.state.db = db
        logger.info("MongoDB 连接成功")

        # 最终由数据库唯一索引保证用户身份与订单幂等约束。
        from app.repositories.address_repository import AddressRepository
        from app.repositories.auth_repository import AuthRepository
        from app.repositories.order_repository import OrderRepository
        await AuthRepository(db).ensure_indexes()
        await AddressRepository(db).ensure_indexes()
        await OrderRepository(db).ensure_indexes()
        logger.info("数据库索引初始化成功")

        # 2. 连接 Redis。限流依赖 Redis，连接失败时拒绝启动。
        logger.info("连接 Redis...")
        redis_client = await startup_redis()
        app.state.redis = redis_client
        logger.info("Redis 连接成功")

        # 3. 启动时生成固定假哈希。
        from app.core.security import initialize_password_security
        await initialize_password_security()
        logger.info("密码安全组件初始化成功")

        # 4. 创建 LLM
        logger.info("初始化 LLM...")
        app.state.llm = create_llm()
        logger.info("LLM 初始化成功")

        logger.info("应用启动完成")
        logger.info("=" * 30)
        yield
    finally:
        logger.info("=" * 30)
        logger.info("应用关闭中...")

        # 按初始化的相反顺序释放资源，一个资源失败不阻断其他资源清理。
        try:
            await shutdown_redis(redis_client)
        except Exception:
            logger.exception("Redis 连接关闭失败")
        try:
            await shutdown_db(mongo_client)
        except Exception:
            logger.exception("MongoDB 连接关闭失败")

        logger.info("应用已关闭")
        logger.info("=" * 30)
