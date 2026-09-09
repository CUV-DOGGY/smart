from app.ports.repositories import ProductRepositoryPort, ShopRepositoryPort
from app.schemas.catalog import ProductListResponse, ShopListResponse
from app.schemas.shop import Shop


class CatalogShopNotFoundError(RuntimeError):
    """目录中不存在指定店铺。"""


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

    async def get_shop(self, shop_id: str) -> Shop:
        """返回单个店铺，使商品页面在直接刷新时也能恢复店铺信息。"""
        shop = await self.shop_repository.find_by_shop_id(shop_id)
        if shop is None or not shop.is_active:
            raise CatalogShopNotFoundError("Shop not found in active catalog")
        return shop

    async def list_products(self, shop_id: str) -> ProductListResponse:
        return ProductListResponse(
            items=await self.product_repository.list_available_by_shop(shop_id)
        )
