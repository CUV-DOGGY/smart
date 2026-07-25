from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.dependencies.auth import get_current_user_id
from app.schemas.order import (
    OrderCreate, OrderCreateResponse, OrderQueryByIdResponse,
    OrderStatusQueryResponse, OrderHistoryQueryResponse,
    OrderCancelRequest, OrderCancelResponse
)
from app.services.order_services import (
    InsufficientStockError,
    OrderServices,
    ProductNotFoundError,
    ProductShopMismatchError,
    ProductUnavailableError,
)
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.dependencies.database import get_db

router = APIRouter(prefix="/orders", tags=["外卖订单"])


def get_order_repository(db=Depends(get_db)) -> OrderRepository:
    return OrderRepository(db)


def get_product_repository(db=Depends(get_db)) -> ProductRepository:
    return ProductRepository(db)


def get_order_service(
    repository: OrderRepository = Depends(get_order_repository),
    product_repository: ProductRepository = Depends(get_product_repository),
) -> OrderServices:
    return OrderServices(repository, product_repository)


@router.post("/create", response_model=OrderCreateResponse)
async def create_order(
    order: OrderCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: OrderServices = Depends(get_order_service),
):
    try:
        return await service.create_order(order, user_id)
    except ProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ProductShopMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except (ProductUnavailableError, InsufficientStockError) as exc:
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
