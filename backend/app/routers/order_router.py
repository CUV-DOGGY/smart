from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.dependencies.auth import get_current_user_id
from app.schemas.order import (
    OrderCreate, OrderCreateResponse, OrderQueryByIdResponse,
    OrderStatusQueryResponse, OrderHistoryQueryResponse,
    OrderCancelRequest, OrderCancelResponse
)
from app.services.order_services import (
    InsufficientStockError,
    IdempotencyKeyConflictError,
    InventoryReservationError,
    MinimumOrderAmountError,
    OrderAddressNotFoundError,
    OrderServices,
    ProductNotFoundError,
    ProductUnavailableError,
    ShopClosedError,
    ShopNotFoundError,
    ShopUnavailableError,
)
from app.repositories.address_repository import AddressRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.shop_repository import ShopRepository
from app.dependencies.database import get_db
from app.services.delivery_location_service import (
    DeliveryLocationService,
    OutsideDeliveryAreaError,
    ShopDeliveryConfigurationError,
)

router = APIRouter(prefix="/orders", tags=["外卖订单"])


def get_order_repository(db=Depends(get_db)) -> OrderRepository:
    return OrderRepository(db)


def get_product_repository(db=Depends(get_db)) -> ProductRepository:
    return ProductRepository(db)


def get_shop_repository(db=Depends(get_db)) -> ShopRepository:
    return ShopRepository(db)


def get_address_repository(db=Depends(get_db)) -> AddressRepository:
    return AddressRepository(db)


def get_order_service(
    repository: OrderRepository = Depends(get_order_repository),
    product_repository: ProductRepository = Depends(get_product_repository),
    shop_repository: ShopRepository = Depends(get_shop_repository),
    address_repository: AddressRepository = Depends(
        get_address_repository
    ),
) -> OrderServices:
    return OrderServices(
        repository,
        product_repository,
        shop_repository,
        address_repository,
        DeliveryLocationService(),
    )


@router.post("/create", response_model=OrderCreateResponse)
async def create_order(
    order: OrderCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
            description="一次下单意图的唯一幂等键",
        ),
    ],
    service: OrderServices = Depends(get_order_service),
):
    try:
        return await service.create_order(
            order,
            user_id,
            idempotency_key=idempotency_key,
        )
    except OrderAddressNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ADDRESS_NOT_FOUND",
                "message": "收货地址不存在",
            },
        ) from exc
    except (ShopNotFoundError, ProductNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ShopDeliveryConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SHOP_DELIVERY_CONFIG_NOT_CONFIGURED",
                "message": "店铺配送位置或配送半径尚未配置",
            },
        ) from exc
    except OutsideDeliveryAreaError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "OUTSIDE_DELIVERY_AREA",
                "message": "收货地址超出店铺配送范围",
                "distance_meters": exc.distance_meters,
                "delivery_radius_meters": (
                    exc.delivery_radius_meters
                ),
            },
        ) from exc
    except (
        IdempotencyKeyConflictError,
        ShopUnavailableError,
        ShopClosedError,
        ProductUnavailableError,
        InsufficientStockError,
        MinimumOrderAmountError,
        InventoryReservationError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get("/query_order_by_id", response_model=OrderQueryByIdResponse)
async def query_order_by_id(
    user_id: Annotated[str, Depends(get_current_user_id)],
    order_id: str = Query(..., min_length=1, description="订单ID"),
    service: OrderServices = Depends(get_order_service),
):
    return await service.query_order_by_id(order_id, user_id)


@router.get("/query_order_status", response_model=OrderStatusQueryResponse)
async def query_order_status(
    user_id: Annotated[str, Depends(get_current_user_id)],
    order_id: str = Query(..., min_length=1, description="订单ID"),
    service: OrderServices = Depends(get_order_service),
):
    return await service.query_order_status(order_id, user_id)

@router.get("/query_order_history", response_model=OrderHistoryQueryResponse)
async def query_order_history(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: OrderServices = Depends(get_order_service),
):
    return await service.query_order_history(user_id)


@router.post("/cancel_order", response_model=OrderCancelResponse)
async def cancel_order(
    request: OrderCancelRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: OrderServices = Depends(get_order_service),
):
    return await service.cancel_order(request.order_id, user_id)
