from fastapi import APIRouter, Depends, Query
from app.schemas.order import OrderCreate, OrderCreateResponse, OrderQueryByIdResponse
from app.services.order_services import OrderServices
from app.repositories.order_repository import OrderRepository
from app.dependencies.database import get_db

router = APIRouter(prefix="/orders", tags=["外卖订单"])


def get_order_repository(db=Depends(get_db)) -> OrderRepository:
    return OrderRepository(db)


def get_order_service(repository: OrderRepository = Depends(get_order_repository)) -> OrderServices:
    return OrderServices(repository)


@router.post("/create", response_model=OrderCreateResponse)
async def create_order(
    order: OrderCreate,
    service: OrderServices = Depends(get_order_service),
):
    return await service.create_order(order)


@router.get("/query_order_by_id", response_model=OrderQueryByIdResponse)
async def query_order_by_id(
    order_id: str = Query(..., min_length=1, description="订单ID"),
    user_id: str = Query(..., min_length=1, description="用户ID"),
    service: OrderServices = Depends(get_order_service),
):
    return await service.query_order_by_id(order_id, user_id)