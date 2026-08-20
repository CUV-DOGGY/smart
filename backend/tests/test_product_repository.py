import unittest
from unittest.mock import AsyncMock, MagicMock

from app.repositories.product_repository import ProductRepository


class ProductRepositoryProjectionTests(unittest.IsolatedAsyncioTestCase):
    def make_repository(self, stored_document):
        collection = MagicMock()
        cursor = MagicMock()
        cursor.sort.return_value = cursor

        def find(_filters, projection, **_kwargs):
            projected = {
                field: value
                for field, value in stored_document.items()
                if projection.get(field) == 1
            }
            cursor.to_list = AsyncMock(return_value=[projected])
            return cursor

        collection.find.side_effect = find
        database = MagicMock()
        database.__getitem__.return_value = collection
        return ProductRepository(database), collection

    async def test_catalog_projection_hides_inventory_and_storage_fields(self):
        repository, collection = self.make_repository(
            {
                "_id": "mongo-id",
                "food_id": "food-001",
                "shop_id": "shop-001",
                "food_name": "演示套餐",
                "price": 32.9,
                "stock": 100,
                "reserved_stock": 5,
                "is_listed": True,
                "is_available": True,
                "updated_at": "future-storage-field",
            }
        )

        products = await repository.list_available_by_shop("shop-001")

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].food_id, "food-001")
        projection = collection.find.call_args.args[1]
        self.assertNotIn("reserved_stock", projection)
        self.assertNotIn("updated_at", projection)

    async def test_order_lookup_reuses_the_product_model_projection(self):
        repository, collection = self.make_repository(
            {
                "food_id": "food-001",
                "shop_id": "shop-001",
                "food_name": "演示套餐",
                "price": 32.9,
                "stock": 100,
                "reserved_stock": 0,
                "is_listed": True,
                "is_available": True,
            }
        )

        products = await repository.find_by_shop_and_food_ids(
            "shop-001",
            ["food-001"],
        )

        self.assertEqual(len(products), 1)
        projection = collection.find.call_args.args[1]
        self.assertNotIn("reserved_stock", projection)
        self.assertEqual(projection["stock"], 1)


if __name__ == "__main__":
    unittest.main()
