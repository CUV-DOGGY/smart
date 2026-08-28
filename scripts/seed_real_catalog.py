"""幂等写入两家真实门店及其代表商品。

真实门店信息核验于 2026-08-28：
- Shake Shack 上海环贸 iapm 店：
  https://shakeshack.com/location/shanghai-iapm
- Shake Shack 上海国金中心店：
  https://shakeshack.com/location/shanghai-ifc

商品名称和价格来自对应门店的近期公开地图目录快照。起送额、配送费、
配送半径、库存及上下架状态是 SmartServe 本地演示环境的业务配置，
不代表品牌或第三方配送平台的实时承诺。
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, MongoClient, UpdateOne


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.config.config import settings  # noqa: E402
from app.schemas.product import Product  # noqa: E402
from app.schemas.shop import Shop  # noqa: E402


DATA_VERIFIED_AT = datetime(2026, 8, 28, tzinfo=UTC)
DEFAULT_STOCK = 100


def weekly_hours(open_time: str, close_time: str) -> list[dict[str, Any]]:
    return [
        {
            "day_of_week": day_of_week,
            "open_time": open_time,
            "close_time": close_time,
        }
        for day_of_week in range(7)
    ]


SHOP_DATA: list[dict[str, Any]] = [
    {
        "shop_id": "shake-shack-shanghai-iapm",
        "shop_name": "Shake Shack（上海环贸 iapm 店）",
        "is_active": True,
        "is_accepting_orders": True,
        "timezone": "Asia/Shanghai",
        "business_hours": weekly_hours("07:00:00", "22:00:00"),
        "minimum_order_amount": 30.0,
        "delivery_fee": 6.0,
        "address": {
            "province": "上海市",
            "city": "上海市",
            "district": "徐汇区",
            "detail_address": "淮海中路999号环贸iapm商场LG1层LG1-142",
        },
        "longitude": 121.458190,
        "latitude": 31.215443,
        "adcode": "310104",
        "formatted_address": (
            "上海市徐汇区淮海中路999号环贸iapm商场LG1层LG1-142"
        ),
        "delivery_radius_meters": 5000,
        "location_updated_at": DATA_VERIFIED_AT,
    },
    {
        "shop_id": "shake-shack-shanghai-ifc",
        "shop_name": "Shake Shack（上海国金中心店）",
        "is_active": True,
        "is_accepting_orders": True,
        "timezone": "Asia/Shanghai",
        "business_hours": weekly_hours("07:00:00", "22:00:00"),
        "minimum_order_amount": 30.0,
        "delivery_fee": 6.0,
        "address": {
            "province": "上海市",
            "city": "上海市",
            "district": "浦东新区",
            "detail_address": "世纪大道8号上海国金中心商场LG1层LG1-36",
        },
        "longitude": 121.502255,
        "latitude": 31.237775,
        "adcode": "310115",
        "formatted_address": (
            "上海市浦东新区世纪大道8号上海国金中心商场LG1层LG1-36"
        ),
        "delivery_radius_meters": 5000,
        "location_updated_at": DATA_VERIFIED_AT,
    },
]


PRODUCT_DATA: list[dict[str, Any]] = [
    {
        "food_id": "iapm-shackburger",
        "shop_id": "shake-shack-shanghai-iapm",
        "food_name": "招牌牛肉堡",
        "price": 49.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
    {
        "food_id": "iapm-cheese-fries",
        "shop_id": "shake-shack-shanghai-iapm",
        "food_name": "芝士薯条",
        "price": 36.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
    {
        "food_id": "iapm-chicken-bites",
        "shop_id": "shake-shack-shanghai-iapm",
        "food_name": "招牌脆鸡块",
        "price": 36.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
    {
        "food_id": "iapm-shroom-beef-burger",
        "shop_id": "shake-shack-shanghai-iapm",
        "food_name": "芝士牛肉蘑菇堡",
        "price": 84.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
    {
        "food_id": "iapm-crispy-chicken-burger",
        "shop_id": "shake-shack-shanghai-iapm",
        "food_name": "香脆鸡肉堡",
        "price": 48.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
    {
        "food_id": "ifc-shackburger",
        "shop_id": "shake-shack-shanghai-ifc",
        "food_name": "招牌牛肉堡",
        "price": 62.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
    {
        "food_id": "ifc-crinkle-cut-fries",
        "shop_id": "shake-shack-shanghai-ifc",
        "food_name": "波浪纹薯条",
        "price": 25.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
    {
        "food_id": "ifc-cheese-fries",
        "shop_id": "shake-shack-shanghai-ifc",
        "food_name": "芝士薯条",
        "price": 36.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
    {
        "food_id": "ifc-vanilla-shake",
        "shop_id": "shake-shack-shanghai-ifc",
        "food_name": "香草奶昔",
        "price": 41.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
    {
        "food_id": "ifc-shroom-beef-burger",
        "shop_id": "shake-shack-shanghai-ifc",
        "food_name": "芝士蘑菇牛肉堡",
        "price": 85.0,
        "stock": DEFAULT_STOCK,
        "is_listed": True,
        "is_available": True,
    },
]


def validated_catalog() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    shops = [Shop.model_validate(item).model_dump() for item in SHOP_DATA]
    products = [
        Product.model_validate(item).model_dump() for item in PRODUCT_DATA
    ]

    shop_ids = {shop["shop_id"] for shop in shops}
    if len(shop_ids) != len(shops):
        raise ValueError("shop_id values must be unique")

    product_keys = {
        (product["shop_id"], product["food_id"])
        for product in products
    }
    if len(product_keys) != len(products):
        raise ValueError("shop_id + food_id values must be unique")

    missing_shop_ids = {
        product["shop_id"] for product in products
    } - shop_ids
    if missing_shop_ids:
        raise ValueError(
            f"products reference missing shops: {sorted(missing_shop_ids)}"
        )

    for shop in shops:
        for business_period in shop["business_hours"]:
            business_period["open_time"] = (
                business_period["open_time"].isoformat()
            )
            business_period["close_time"] = (
                business_period["close_time"].isoformat()
            )

    return shops, products


def seed_catalog() -> None:
    shops, products = validated_catalog()
    client = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        database = client[settings.MONGODB_DB_NAME]
        database.shops.create_index(
            [("shop_id", ASCENDING)],
            unique=True,
            name="uq_shop_id",
        )
        database.products.create_index(
            [("shop_id", ASCENDING), ("food_id", ASCENDING)],
            unique=True,
            name="uq_shop_food_id",
        )

        shop_result = database.shops.bulk_write(
            [
                UpdateOne(
                    {"shop_id": shop["shop_id"]},
                    {"$set": shop},
                    upsert=True,
                )
                for shop in shops
            ]
        )

        product_operations = []
        for product in products:
            product_fields = {
                key: value
                for key, value in product.items()
                if key != "stock"
            }
            product_operations.append(
                UpdateOne(
                    {
                        "shop_id": product["shop_id"],
                        "food_id": product["food_id"],
                    },
                    {
                        "$set": product_fields,
                        "$setOnInsert": {
                            "stock": product["stock"],
                            "reserved_stock": 0,
                        },
                    },
                    upsert=True,
                )
            )
        product_result = database.products.bulk_write(product_operations)

        print(
            "Seeded catalog: "
            f"shops matched={shop_result.matched_count}, "
            f"inserted={shop_result.upserted_count}; "
            f"products matched={product_result.matched_count}, "
            f"inserted={product_result.upserted_count}."
        )
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate or seed the real-store demo catalog."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the catalog without writing to MongoDB",
    )
    arguments = parser.parse_args()

    if arguments.dry_run:
        shops, products = validated_catalog()
        print(
            f"Catalog is valid: {len(shops)} shops, "
            f"{len(products)} products."
        )
        return
    seed_catalog()


if __name__ == "__main__":
    main()
