"""Application composition root for request-scoped business services.

Routers depend only on these factories and application services.  Concrete
MongoDB adapters are assembled here so neither HTTP handlers nor services need
to know which persistence implementation is active.
"""

from fastapi import Depends, Request

from app.agents.runtime import AgentRuntimeContext
from app.config import settings
from app.dependencies.database import get_db
from app.dependencies.geocoding import get_delivery_location_service
from app.repositories.address_repository import AddressRepository
from app.repositories.auth_repository import AuthRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.shop_repository import ShopRepository
from app.repositories.write_command_repository import WriteCommandRepository
from app.services.address_service import AddressService
from app.services.auth_service import AuthService
from app.services.catalog_service import CatalogService
from app.services.chat_service import AgentChatService
from app.services.conversation_service import ConversationService
from app.services.delivery_location_service import DeliveryLocationService
from app.services.order_service import OrderService
from app.services.write_command_executor import WriteCommandExecutor
from app.services.write_command_service import WriteCommandService
from app.tools.service_tools import ServiceToolRegistry


def get_auth_service(db=Depends(get_db)) -> AuthService:
    return AuthService(AuthRepository(db))


def get_address_service(
    db=Depends(get_db),
    delivery_location_service: DeliveryLocationService = Depends(
        get_delivery_location_service
    ),
) -> AddressService:
    return AddressService(AddressRepository(db), delivery_location_service)


def get_catalog_service(db=Depends(get_db)) -> CatalogService:
    return CatalogService(ShopRepository(db), ProductRepository(db))


def get_order_service(db=Depends(get_db)) -> OrderService:
    return OrderService(
        OrderRepository(db),
        ProductRepository(db),
        ShopRepository(db),
        AddressRepository(db),
        DeliveryLocationService(),
    )


def get_conversation_service(db=Depends(get_db)) -> ConversationService:
    return ConversationService(ConversationRepository(db))


def get_agent_chat_service(
    request: Request,
    db=Depends(get_db),
) -> AgentChatService:
    delivery_service = DeliveryLocationService()
    address_service = AddressService(AddressRepository(db), delivery_service)
    catalog_service = CatalogService(ShopRepository(db), ProductRepository(db))
    order_service = OrderService(
        OrderRepository(db),
        ProductRepository(db),
        ShopRepository(db),
        AddressRepository(db),
        delivery_service,
    )
    tools = ServiceToolRegistry(
        catalog_service=catalog_service,
        address_service=address_service,
        order_service=order_service,
    )
    command_repository = WriteCommandRepository(db)
    command_service = WriteCommandService(
        command_repository,
        tools,
        confirmation_ttl_seconds=settings.WRITE_COMMAND_CONFIRMATION_TTL_SECONDS,
    )
    command_executor = WriteCommandExecutor(
        command_repository,
        tools,
        lease_seconds=settings.WRITE_COMMAND_EXECUTION_LEASE_SECONDS,
    )
    runtime = AgentRuntimeContext(
        user_id="",
        llm=request.app.state.llm,
        tools=tools,
        command_service=command_service,
    )
    return AgentChatService(
        ConversationRepository(db),
        request.app.state.agent_runner,
        request.app.state.conversation_lock,
        runtime,
        command_service,
        command_executor,
        timeout_seconds=settings.AGENT_RUN_TIMEOUT_SECONDS,
    )
