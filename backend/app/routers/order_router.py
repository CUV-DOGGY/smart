from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis

from app.config import settings
from app.dependencies.auth import get_current_user_id
from app.dependencies.cache import get_redis
from app.schemas.order import (
    OrderCreate, OrderCreateResponse, OrderQueryByIdResponse,
    OrderStatusQueryResponse, OrderHistoryQueryResponse,
    OrderCancelRequest, OrderCancelResponse
)
from app.services.order_services import (
    InsufficientStockError,
    InventoryReservationError,
    MinimumOrderAmountError,
    OrderServices,
    ProductNotFoundError,
    ProductUnavailableError,
    ShopClosedError,
    ShopNotFoundError,
    ShopUnavailableError,
)
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.shop_repository import ShopRepository
from app.dependencies.database import get_db
from app.services.amap_service import (
    AmapGeocodingService,
    AmapServiceUnavailableError,
)
from app.services.delivery_location_service import (
    AddressNeedsMapPickError,
    DeliveryLocationService,
    OutsideDeliveryAreaError,
    ShopDeliveryConfigurationError,
)
from app.services.delivery_geocoding_rate_limiter import (
    DeliveryGeocodingRateLimitBackendError,
    DeliveryGeocodingRateLimitExceeded,
    DeliveryGeocodingRateLimiter,
)

router = APIRouter(prefix="/orders", tags=["外卖订单"])


def get_order_repository(db=Depends(get_db)) -> OrderRepository:
    return OrderRepository(db)


def get_product_repository(db=Depends(get_db)) -> ProductRepository:
    return ProductRepository(db)


def get_shop_repository(db=Depends(get_db)) -> ShopRepository:
    return ShopRepository(db)


def get_amap_geocoding_service(
    redis: Annotated[Redis, Depends(get_redis)],
) -> AmapGeocodingService:
    return AmapGeocodingService(
        key=settings.AMAP_WEB_SERVICE_KEY.get_secret_value(),
        connect_timeout_seconds=settings.AMAP_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=settings.AMAP_READ_TIMEOUT_SECONDS,
        max_retries=settings.AMAP_MAX_RETRIES,
        cache_seconds=settings.AMAP_GEOCODE_CACHE_SECONDS,
        cache_secret=(
            settings.RATE_LIMIT_KEY_SECRET
            or settings.JWT_SECRET_KEY
        ),
        redis=redis,
    )


def get_delivery_location_service(
    amap_service: Annotated[
        AmapGeocodingService,
        Depends(get_amap_geocoding_service),
    ],
) -> DeliveryLocationService:
    return DeliveryLocationService(amap_service)


def get_delivery_geocoding_rate_limiter(
    redis: Annotated[Redis, Depends(get_redis)],
) -> DeliveryGeocodingRateLimiter:
    return DeliveryGeocodingRateLimiter(redis)


def get_order_service(
    repository: OrderRepository = Depends(get_order_repository),
    product_repository: ProductRepository = Depends(get_product_repository),
    shop_repository: ShopRepository = Depends(get_shop_repository),
    delivery_location_service: DeliveryLocationService = Depends(
        get_delivery_location_service
    ),
) -> OrderServices:
    return OrderServices(
        repository,
        product_repository,
        shop_repository,
        delivery_location_service,
    )


@router.post("/create", response_model=OrderCreateResponse)
async def create_order(
    order: OrderCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: OrderServices = Depends(get_order_service),
    geocoding_rate_limiter: DeliveryGeocodingRateLimiter = Depends(
        get_delivery_geocoding_rate_limiter
    ),
):
    try:
        await geocoding_rate_limiter.check(user_id)
        return await service.create_order(order, user_id)
    except DeliveryGeocodingRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="地址解析请求过于频繁，请稍后重试",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except DeliveryGeocodingRateLimitBackendError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="地址解析限流服务暂时不可用",
        ) from exc
    except AddressNeedsMapPickError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ADDRESS_NEEDS_MAP_PICK",
                "message": "收货地址需要通过地图选点确认",
            },
        ) from exc
    except AmapServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "GEOCODING_SERVICE_UNAVAILABLE",
                "message": "地址解析服务暂时不可用",
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
