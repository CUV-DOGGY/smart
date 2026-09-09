from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import redis.asyncio as redis
from fastapi import FastAPI
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import settings
from app.integrations.llm import create_llm
from app.observability import shutdown_observability

if TYPE_CHECKING:
    from app.agents import AgentRunner
    from app.integrations.conversation_lock import ConversationRunLock
    from app.integrations.write_command_worker import WriteCommandWorker

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentResources:
    checkpointer: Any
    runner: AgentRunner
    conversation_lock: ConversationRunLock


# ==================== 启动时初始化 ====================
async def startup_db() -> tuple[AsyncMongoClient, AsyncDatabase]:
    """连接 MongoDB"""

    # 创建MongoDB客户端
    client = AsyncMongoClient(settings.MONGODB_URL)

    try:
        await client.admin.command("ping")
    except Exception:
        await client.close()
        raise
    # 获取集合
    db = client[settings.MONGODB_DB_NAME]
    return client, db


async def startup_redis():
    """连接 Redis"""

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


async def startup_indexes(db: AsyncDatabase) -> None:
    """创建数据库唯一索引和查询索引。"""
    from app.repositories.address_repository import AddressRepository
    from app.repositories.auth_repository import AuthRepository
    from app.repositories.conversation_repository import ConversationRepository
    from app.repositories.order_repository import OrderRepository
    from app.repositories.product_repository import ProductRepository
    from app.repositories.shop_repository import ShopRepository
    from app.repositories.write_command_repository import WriteCommandRepository

    await AuthRepository(db).ensure_indexes()
    await AddressRepository(db).ensure_indexes()
    await OrderRepository(db).ensure_indexes()
    await ConversationRepository(db).ensure_indexes()
    await ShopRepository(db).ensure_indexes()
    await ProductRepository(db).ensure_indexes()
    await WriteCommandRepository(db).ensure_indexes()


# Worker启动函数
def startup_write_command_worker(db: AsyncDatabase) -> WriteCommandWorker:
    """创建并启动写命令恢复 Worker。"""
    from app.integrations.write_command_worker import WriteCommandWorker
    from app.repositories.address_repository import AddressRepository
    from app.repositories.order_repository import OrderRepository
    from app.repositories.product_repository import ProductRepository
    from app.repositories.shop_repository import ShopRepository
    from app.repositories.write_command_repository import WriteCommandRepository
    from app.services.address_service import AddressService
    from app.services.catalog_service import CatalogService
    from app.services.delivery_location_service import DeliveryLocationService
    from app.services.order_service import OrderService
    from app.services.write_command_executor import WriteCommandExecutor
    from app.tools.service_tools import ServiceToolRegistry

    delivery_service = DeliveryLocationService()

    worker_tools = ServiceToolRegistry(
        catalog_service=CatalogService(
            ShopRepository(db),
            ProductRepository(db),
        ),
        address_service=AddressService(
            AddressRepository(db),
            delivery_service,
        ),
        order_service=OrderService(
            OrderRepository(db),
            ProductRepository(db),
            ShopRepository(db),
            AddressRepository(db),
            delivery_service,
        ),
    )

    command_repository = WriteCommandRepository(db)

    command_executor = WriteCommandExecutor(
        command_repository,
        worker_tools,
        lease_seconds=(settings.WRITE_COMMAND_EXECUTION_LEASE_SECONDS),
    )

    worker = WriteCommandWorker(
        command_repository,
        command_executor,
    )
    worker.start()

    return worker


# 编译一次持久化 Agent 图；运行时业务依赖按请求注入。
def startup_agent_resources(
    redis_client,
) -> AgentResources:
    """创建持久化 Agent 图和会话锁。"""
    from app.agents import AgentRunner, build_service_agent
    from app.integrations.agent_checkpoint import create_agent_checkpointer
    from app.integrations.conversation_lock import ConversationRunLock

    checkpointer = create_agent_checkpointer(
        settings.MONGODB_URL,
        settings.MONGODB_DB_NAME,
    )

    try:
        graph = build_service_agent(checkpointer)
        runner = AgentRunner(graph, checkpointer)

        conversation_lock = ConversationRunLock(
            redis_client,
            lease_seconds=settings.AGENT_LOCK_LEASE_SECONDS,
        )

        return AgentResources(
            checkpointer=checkpointer,
            runner=runner,
            conversation_lock=conversation_lock,
        )
    except Exception:
        checkpointer.close()
        raise


# ==================== 关闭时清理 ====================
async def shutdown_db(client: AsyncMongoClient | None) -> None:
    """断开 MongoDB"""
    if client is not None:
        await client.close()


async def shutdown_redis(redis_client):
    """断开 Redis"""
    if redis_client is not None:
        await redis_client.aclose()


def shutdown_agent_resources(
    resources: AgentResources | None,
) -> None:
    if resources is not None:
        resources.checkpointer.close()


# ==================== Lifespan ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 30)
    logger.info("应用启动中...")
    mongo_client = None
    redis_client = None
    agent_resources = None
    write_command_worker = None
    http_client = None

    try:
        # 1. 连接 MongoDB
        logger.info("连接 MongoDB...")
        mongo_client, db = await startup_db()
        app.state.mongo_client = mongo_client
        app.state.db = db
        logger.info("MongoDB 连接成功")

        # 最终由数据库唯一索引保证用户身份与订单幂等约束。
        await startup_indexes(db)
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

        # 4. 创建共享 HTTP 客户端和 LLM。
        logger.info("初始化 HTTP 客户端和 LLM...")
        http_client = httpx.AsyncClient()
        app.state.http_client = http_client
        app.state.llm = create_llm(http_async_client=http_client)
        logger.info("HTTP 客户端和 LLM 初始化成功")

        # 5. 初始化Agent
        logger.info("初始化 LangGraph Agent...")

        agent_resources = startup_agent_resources(
            redis_client,
        )

        app.state.agent_runner = agent_resources.runner
        app.state.conversation_lock = agent_resources.conversation_lock

        logger.info("LangGraph Agent 初始化成功")

        # 6. 正常确认在请求内执行；恢复 Worker 只接管超时租约或遗留任务。

        write_command_worker = startup_write_command_worker(db)
        app.state.write_command_worker = write_command_worker
        logger.info("写命令恢复 Worker 初始化成功")

        logger.info("应用启动完成")
        logger.info("=" * 30)
        yield
    finally:
        logger.info("=" * 30)
        logger.info("应用关闭中...")

        # 按初始化的相反顺序释放资源，一个资源失败不阻断其他资源清理。
        try:
            if write_command_worker is not None:
                await write_command_worker.stop()
        except Exception:
            logger.exception("写命令恢复 Worker 关闭失败")
        try:
            shutdown_agent_resources(agent_resources)
        except Exception:
            logger.exception("Agent Checkpoint 连接关闭失败")
        try:
            if http_client is not None:
                await http_client.aclose()
        except Exception:
            logger.exception("HTTP 客户端关闭失败")
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
        shutdown_observability(app)
