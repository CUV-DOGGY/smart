from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.dependencies.services import get_catalog_service
from app.schemas.catalog import ProductListResponse, ShopListResponse
from app.services.catalog_service import CatalogService


router = APIRouter(prefix="/catalog", tags=["店铺与商品"])


@router.get("/shops", response_model=ShopListResponse)
async def list_shops(
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ShopListResponse:
    return await service.list_shops()


@router.get(
    "/shops/{shop_id}/products",
    response_model=ProductListResponse,
)
async def list_products(
    shop_id: Annotated[str, Path(min_length=1, max_length=64)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ProductListResponse:
    return await service.list_products(shop_id)
