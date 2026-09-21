import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

if TYPE_CHECKING:
    from app.plugins.business_hours import BusinessHoursConfig

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
    from app.integrations.llm import create_llm as _create_llm

    return _create_llm()


async def startup_plugins(
    business_hours_config: "BusinessHoursConfig | None" = None,
):
    """创建并启动应用插件"""
    from app.plugins import (
        PluginContext,
        PluginManager,
        PluginToolRegistry,
    )
    from app.plugins.business_hours import BusinessHoursConfig, BusinessHoursPlugin

    config = business_hours_config or BusinessHoursConfig(
        timezone=settings.BUSINESS_HOURS_TIMEZONE,
        business_days=tuple(settings.BUSINESS_HOURS_DAYS),
        open_time=settings.BUSINESS_HOURS_OPEN_TIME,
        close_time=settings.BUSINESS_HOURS_CLOSE_TIME,
    )

    plugin_tools = PluginToolRegistry()
    plugin_manager = PluginManager(
        [
            BusinessHoursPlugin(config),
        ]
    )

    await plugin_manager.start(
        PluginContext(
            logger=logger,
            tools=plugin_tools,
        )
    )

    return plugin_manager, plugin_tools


# ==================== 关闭时清理 ====================
async def shutdown_db(client):
    """断开 MongoDB"""
    if client:
        client.close()


async def shutdown_redis(redis_client):
    """断开 Redis"""
    if redis_client:
        await redis_client.aclose()


async def shutdown_plugins(plugin_manager):
    """按插件管理器记录的逆序停止插件"""
    if plugin_manager:
        await plugin_manager.stop()


# ==================== Lifespan ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 30)
    logger.info("应用启动中...")
    mongo_client = None
    redis_client = None
    checkpointer = None
    plugin_manager = None
    plugin_tools = None

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
        from app.repositories.conversation_repository import ConversationRepository
        from app.repositories.product_repository import ProductRepository
        from app.repositories.shop_repository import ShopRepository

        await AuthRepository(db).ensure_indexes()
        await AddressRepository(db).ensure_indexes()
        await OrderRepository(db).ensure_indexes()
        await ConversationRepository(db).ensure_indexes()
        await ShopRepository(db).ensure_indexes()
        await ProductRepository(db).ensure_indexes()
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

        # 5. 编译一次持久化 Agent 图；运行时业务依赖按请求注入。
        from app.agents import AgentRunner, build_service_agent
        from app.integrations.agent_checkpoint import create_agent_checkpointer
        from app.integrations.conversation_lock import ConversationRunLock

        checkpointer = create_agent_checkpointer(
            settings.MONGODB_URL,
            settings.MONGODB_DB_NAME,
        )
        graph = build_service_agent(checkpointer)
        agent_runner = AgentRunner(graph, checkpointer)
        app.state.agent_runner = agent_runner
        app.state.conversation_lock = ConversationRunLock(
            redis_client,
            lease_seconds=settings.AGENT_LOCK_LEASE_SECONDS,
        )
        logger.info("LangGraph Agent 初始化成功")
        # 6. 在主体依赖就绪后启动插件。
        logger.info("初始化插件...")
        plugin_manager, plugin_tools = await startup_plugins()

        app.state.plugin_manager = plugin_manager
        app.state.plugin_tools = plugin_tools

        logger.info("插件初始化成功")

        logger.info("应用启动完成")
        logger.info("=" * 30)
        yield
    finally:
        logger.info("=" * 30)
        logger.info("应用关闭中...")

        # 按初始化的相反顺序释放资源，一个资源失败不阻断其他资源清理。
        try:
            await shutdown_plugins(plugin_manager)
        except Exception:
            logger.exception("插件关闭失败")
        try:
            await shutdown_redis(redis_client)
        except Exception:
            logger.exception("Redis 连接关闭失败")
        try:
            if checkpointer is not None:
                checkpointer.close()
        except Exception:
            logger.exception("Agent Checkpoint 连接关闭失败")
        try:
            await shutdown_db(mongo_client)
        except Exception:
            logger.exception("MongoDB 连接关闭失败")

        logger.info("应用已关闭")
        logger.info("=" * 30)
