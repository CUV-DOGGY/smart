from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.dependencies.database import get_db
from app.repositories.product_repository import ProductRepository
from app.repositories.shop_repository import ShopRepository
from app.schemas.catalog import ProductListResponse, ShopListResponse


router = APIRouter(prefix="/catalog", tags=["店铺与商品"])


@router.get("/shops", response_model=ShopListResponse)
async def list_shops(db=Depends(get_db)) -> ShopListResponse:
    return ShopListResponse(items=await ShopRepository(db).list_active())


@router.get(
    "/shops/{shop_id}/products",
    response_model=ProductListResponse,
)
async def list_products(
    shop_id: Annotated[str, Path(min_length=1, max_length=64)],
    db=Depends(get_db),
) -> ProductListResponse:
    products = await ProductRepository(db).list_available_by_shop(shop_id)
    return ProductListResponse(items=products)
