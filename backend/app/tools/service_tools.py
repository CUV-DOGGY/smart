from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.order import OrderCreate, OrderCreateItem
from app.services.address_service import AddressNotFoundError, AddressService
from app.services.catalog_service import CatalogService
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


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArguments(ToolArguments):
    pass


class ShopArguments(ToolArguments):
    shop_id: str | None = Field(default=None, min_length=1, max_length=64)


class OrderArguments(ToolArguments):
    order_id: str | None = Field(default=None, min_length=1, max_length=64)


class AddressArguments(ToolArguments):
    address_id: str | None = Field(default=None, min_length=1, max_length=64)


class CreateOrderArguments(ToolArguments):
    shop_id: str | None = Field(default=None, min_length=1, max_length=64)
    address_id: str | None = Field(default=None, min_length=1, max_length=64)
    items: list[OrderCreateItem] | None = Field(default=None, max_length=50)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments_model: type[ToolArguments]
    required_fields: tuple[str, ...]
    is_write: bool = False

    def openai_schema(self) -> dict[str, Any]:
        parameters = self.arguments_model.model_json_schema()
        parameters.pop("title", None)
        # Partial calls are intentional: the graph validates and asks for missing slots.
        parameters["required"] = []
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


SPECS = {
    spec.name: spec
    for spec in (
        ToolSpec("list_shops", "列出当前可下单店铺。", NoArguments, ()),
        ToolSpec("list_products", "查询指定店铺可售商品；缺少店铺ID也应调用。", ShopArguments, ("shop_id",)),
        ToolSpec("list_addresses", "列出当前登录用户的收货地址。", NoArguments, ()),
        ToolSpec("list_orders", "列出当前登录用户最近的订单。", NoArguments, ()),
        ToolSpec("get_order", "查询当前用户的一笔订单；缺少订单ID也应调用。", OrderArguments, ("order_id",)),
        ToolSpec("create_order", "创建真实订单；缺少店铺、地址或商品时也应调用。", CreateOrderArguments, ("shop_id", "address_id", "items"), True),
        ToolSpec("cancel_order", "申请取消真实订单；缺少订单ID也应调用。", OrderArguments, ("order_id",), True),
        ToolSpec("set_default_address", "把已有地址设置为默认地址。", AddressArguments, ("address_id",), True),
        ToolSpec("delete_address", "删除已有收货地址。", AddressArguments, ("address_id",), True),
    )
}


class ToolValidationFailure(RuntimeError):
    pass


class ServiceToolRegistry:
    def __init__(
        self,
        *,
        catalog_service: CatalogService,
        address_service: AddressService,
        order_service: OrderService,
    ) -> None:
        self.catalog_service = catalog_service
        self.address_service = address_service
        self.order_service = order_service

    @staticmethod
    def definitions() -> list[dict[str, Any]]:
        return [spec.openai_schema() for spec in SPECS.values()]

    @staticmethod
    def validate(name: str, arguments: dict[str, Any]) -> tuple[dict, list[str]]:
        spec = SPECS.get(name)
        if spec is None:
            raise ToolValidationFailure("UNKNOWN_TOOL")
        try:
            normalized = spec.arguments_model.model_validate(arguments).model_dump(
                exclude_none=True,
                mode="json",
            )
        except ValidationError as exc:
            raise ToolValidationFailure("INVALID_TOOL_ARGUMENTS") from exc
        missing = [field for field in spec.required_fields if not normalized.get(field)]
        return normalized, missing

    @staticmethod
    def is_write(name: str) -> bool:
        spec = SPECS.get(name)
        return bool(spec and spec.is_write)

    @staticmethod
    def confirmation_summary(name: str, arguments: dict[str, Any]) -> str:
        if name == "create_order":
            item_text = "、".join(
                f"{item['food_id']} × {item['quantity']}"
                for item in arguments.get("items", [])
            )
            return f"创建订单：店铺 {arguments['shop_id']}，地址 {arguments['address_id']}，商品 {item_text}"
        if name == "cancel_order":
            return f"申请取消订单 {arguments['order_id']}"
        if name == "set_default_address":
            return f"将地址 {arguments['address_id']} 设为默认地址"
        if name == "delete_address":
            return f"删除地址 {arguments['address_id']}"
        raise ToolValidationFailure("TOOL_DOES_NOT_REQUIRE_CONFIRMATION")

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        user_id: str,
        action_id: str,
    ) -> dict[str, Any]:
        try:
            if name == "list_shops":
                result = await self.catalog_service.list_shops()
                return {"ok": True, "items": result.model_dump(mode="json")["items"]}
            if name == "list_products":
                result = await self.catalog_service.list_products(arguments["shop_id"])
                return {"ok": True, "items": result.model_dump(mode="json")["items"]}
            if name == "list_addresses":
                result = await self.address_service.list_addresses(user_id)
                items = []
                for address in result.addresses:
                    item = address.model_dump(mode="json")
                    phone = item.get("receiver_phone", "")
                    item["receiver_phone"] = phone[:3] + "****" + phone[-4:] if len(phone) == 11 else "***"
                    items.append(item)
                return {"ok": True, "items": items}
            if name == "list_orders":
                items, _ = await self.order_service.list_orders_page(
                    user_id, limit=20, cursor=None
                )
                return {"ok": True, "items": [item.model_dump(mode="json") for item in items]}
            if name == "get_order":
                result = await self.order_service.query_order_by_id(arguments["order_id"], user_id)
                if result.order is None:
                    return {"ok": False, "code": "ORDER_NOT_FOUND", "message": "订单不存在或无权访问"}
                return {"ok": True, "order": result.order.model_dump(mode="json", exclude={"user_id"})}
            if name == "create_order":
                request = OrderCreate.model_validate(arguments)
                result = await self.order_service.create_order(
                    request,
                    user_id,
                    idempotency_key=f"agent:{action_id}",
                )
                return {"ok": True, "order": result.model_dump(mode="json", exclude={"status", "message"})}
            if name == "cancel_order":
                result = await self.order_service.cancel_order(arguments["order_id"], user_id)
                return {"ok": True, "order_id": arguments["order_id"], "order_status": result.order_status.value}
            if name == "set_default_address":
                result = await self.address_service.set_default(arguments["address_id"], user_id)
                return {"ok": True, "address": result.address.model_dump(mode="json", exclude={"receiver_phone"})}
            if name == "delete_address":
                await self.address_service.delete_address(arguments["address_id"], user_id)
                return {"ok": True, "address_id": arguments["address_id"]}
        except (AddressNotFoundError, OrderAddressNotFoundError):
            return {"ok": False, "code": "ADDRESS_NOT_FOUND", "message": "收货地址不存在"}
        except OrderNotFoundError:
            return {"ok": False, "code": "ORDER_NOT_FOUND", "message": "订单不存在或无权访问"}
        except OrderStateConflictError:
            return {"ok": False, "code": "ORDER_STATE_CONFLICT", "message": "当前订单状态不允许该操作"}
        except ShopNotFoundError:
            return {"ok": False, "code": "SHOP_NOT_FOUND", "message": "店铺不存在"}
        except ProductNotFoundError:
            return {"ok": False, "code": "PRODUCT_NOT_FOUND", "message": "部分商品不存在"}
        except ShopUnavailableError:
            return {"ok": False, "code": "SHOP_UNAVAILABLE", "message": "店铺当前不可接单"}
        except ShopClosedError:
            return {"ok": False, "code": "SHOP_CLOSED", "message": "店铺当前不在营业时间"}
        except ProductUnavailableError:
            return {"ok": False, "code": "PRODUCT_UNAVAILABLE", "message": "部分商品当前不可售"}
        except InsufficientStockError:
            return {"ok": False, "code": "INSUFFICIENT_STOCK", "message": "商品库存不足"}
        except MinimumOrderAmountError:
            return {"ok": False, "code": "MINIMUM_ORDER_AMOUNT", "message": "未达到最低起送金额"}
        except InventoryReservationError:
            return {"ok": False, "code": "INVENTORY_CHANGED", "message": "库存已变化，请重试"}
        except IdempotencyKeyConflictError:
            return {"ok": False, "code": "IDEMPOTENCY_KEY_CONFLICT", "message": "操作幂等键冲突"}
        except ShopDeliveryConfigurationError:
            return {"ok": False, "code": "SHOP_DELIVERY_CONFIG_NOT_CONFIGURED", "message": "店铺配送范围尚未配置"}
        except OutsideDeliveryAreaError:
            return {"ok": False, "code": "OUTSIDE_DELIVERY_AREA", "message": "收货地址超出配送范围"}
        raise ToolValidationFailure("UNKNOWN_TOOL")
