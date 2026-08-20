from app.ports.repositories import ProductRepositoryPort, ShopRepositoryPort
from app.schemas.catalog import ProductListResponse, ShopListResponse


class CatalogService:
    def __init__(
        self,
        shop_repository: ShopRepositoryPort,
        product_repository: ProductRepositoryPort,
    ) -> None:
        self.shop_repository = shop_repository
        self.product_repository = product_repository

    async def list_shops(self) -> ShopListResponse:
        return ShopListResponse(items=await self.shop_repository.list_active())

    async def list_products(self, shop_id: str) -> ProductListResponse:
        return ProductListResponse(
            items=await self.product_repository.list_available_by_shop(shop_id)
        )
