from pydantic import BaseModel, ConfigDict, Field


class Product(BaseModel):
    """商品集合中的可信商品数据。"""

    model_config = ConfigDict(extra="forbid")

    food_id: str = Field(min_length=1, max_length=64)
    shop_id: str = Field(min_length=1, max_length=64)
    food_name: str = Field(min_length=1, max_length=200)
    price: float = Field(ge=0, allow_inf_nan=False)
    stock: int = Field(ge=0)
    is_listed: bool
    is_available: bool
