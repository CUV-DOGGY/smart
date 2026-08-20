from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, status

from app.core.api_errors import ApiError
from app.dependencies.auth import get_current_user_id
from app.dependencies.services import get_order_service
from app.schemas.order import (
    OrderCancelResult,
    OrderCreate,
    OrderCreateResult,
    OrderHistoryPage,
    OrderQueryByIdData,
)
from app.services.delivery_location_service import (
    OutsideDeliveryAreaError,
    ShopDeliveryConfigurationError,
)
from app.services.order_service import (
    IdempotencyKeyConflictError,
    InsufficientStockError,
    InventoryReservationError,
    MinimumOrderAmountError,
    OrderAddressNotFoundError,
    OrderNotFoundError,
    OrderService,
    OrderStateConflictError,
    ProductNotFoundError,
    ProductUnavailableError,
    ShopClosedError,
    ShopNotFoundError,
    ShopUnavailableError,
)


router = APIRouter(prefix="/orders", tags=["外卖订单"])


@router.post(
    "",
    response_model=OrderCreateResult,
    status_code=status.HTTP_201_CREATED,
)
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
        ),
    ],
    service: OrderService = Depends(get_order_service),
) -> OrderCreateResult:
    try:
        response = await service.create_order(
            order,
            user_id,
            idempotency_key=idempotency_key,
        )
    except OrderAddressNotFoundError as exc:
        raise _api_error(404, "ADDRESS_NOT_FOUND", "收货地址不存在") from exc
    except ShopNotFoundError as exc:
        raise _api_error(404, "SHOP_NOT_FOUND", "店铺不存在") from exc
    except ProductNotFoundError as exc:
        raise _api_error(404, "PRODUCT_NOT_FOUND", "部分商品不存在") from exc
    except ShopDeliveryConfigurationError as exc:
        raise _api_error(
            409,
            "SHOP_DELIVERY_CONFIG_NOT_CONFIGURED",
            "店铺配送位置或配送半径尚未配置",
        ) from exc
    except OutsideDeliveryAreaError as exc:
        raise _api_error(409, "OUTSIDE_DELIVERY_AREA", "收货地址超出配送范围") from exc
    except IdempotencyKeyConflictError as exc:
        raise _api_error(409, "IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于其他订单") from exc
    except ShopUnavailableError as exc:
        raise _api_error(409, "SHOP_UNAVAILABLE", "店铺当前不可接单") from exc
    except ShopClosedError as exc:
        raise _api_error(409, "SHOP_CLOSED", "店铺当前不在营业时间") from exc
    except ProductUnavailableError as exc:
        raise _api_error(409, "PRODUCT_UNAVAILABLE", "部分商品当前不可售") from exc
    except InsufficientStockError as exc:
        raise _api_error(409, "INSUFFICIENT_STOCK", "商品库存不足") from exc
    except MinimumOrderAmountError as exc:
        raise _api_error(409, "MINIMUM_ORDER_AMOUNT", "未达到最低起送金额") from exc
    except InventoryReservationError as exc:
        raise _api_error(409, "INVENTORY_CHANGED", "库存已发生变化，请重试") from exc
    return OrderCreateResult.model_validate(
        response.model_dump(exclude={"status", "message"})
    )


@router.get("", response_model=OrderHistoryPage)
async def list_orders(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[OrderService, Depends(get_order_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> OrderHistoryPage:
    try:
        items, next_cursor = await service.list_orders_page(
            user_id,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise _api_error(422, "INVALID_CURSOR", "分页游标无效") from exc
    return OrderHistoryPage(
        items=items,
        next_cursor=next_cursor,
    )


@router.get("/{order_id}", response_model=OrderQueryByIdData)
async def get_order(
    order_id: Annotated[str, Path(min_length=1, max_length=64)],
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: OrderService = Depends(get_order_service),
) -> OrderQueryByIdData:
    response = await service.query_order_by_id(order_id, user_id)
    if response.order is None:
        raise _api_error(404, "ORDER_NOT_FOUND", "订单不存在或无权访问")
    return response.order


@router.post("/{order_id}/cancel", response_model=OrderCancelResult)
async def cancel_order(
    order_id: Annotated[str, Path(min_length=1, max_length=64)],
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: OrderService = Depends(get_order_service),
) -> OrderCancelResult:
    try:
        response = await service.cancel_order(order_id, user_id)
    except OrderNotFoundError as exc:
        raise _api_error(404, "ORDER_NOT_FOUND", "订单不存在或无权访问") from exc
    except OrderStateConflictError as exc:
        raise _api_error(409, "ORDER_STATE_CONFLICT", "当前订单状态无法取消") from exc
    return OrderCancelResult(
        order_id=order_id,
        order_status=response.order_status,
    )


def _api_error(status_code: int, code: str, message: str) -> ApiError:
    return ApiError(status_code=status_code, code=code, message=message)
