from pydantic import BaseModel

from app.schemas.product import Product
from app.schemas.shop import Shop


class ShopListResponse(BaseModel):
    items: list[Shop]


class ProductListResponse(BaseModel):
    items: list[Product]

