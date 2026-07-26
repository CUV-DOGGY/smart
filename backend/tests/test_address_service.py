import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from app.schemas.address import UserAddress, UserAddressCreate
from app.schemas.delivery import GeocodingResult
from app.services.address_service import (
    AddressLimitExceededError,
    AddressNotFoundError,
    AddressService,
)
from app.services.amap_service import AmapServiceUnavailableError
from app.services.delivery_location_service import DeliveryLocationService


TEST_NOW = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)


class FakeAmapService:
    def __init__(self, reverse_unavailable: bool = False):
        self.reverse_unavailable = reverse_unavailable
        self.geocode_count = 0
        self.reverse_geocode_count = 0

    async def geocode(self, address):
        self.geocode_count += 1
        return GeocodingResult(
            longitude=116.001,
            latitude=39.0,
            formatted_address=address.full_address(),
            province=address.province,
            city=address.city,
            district=address.district,
            adcode="110105",
        )

    async def reverse_geocode(self, *, longitude: float, latitude: float):
        self.reverse_geocode_count += 1
        if self.reverse_unavailable:
            raise AmapServiceUnavailableError("unavailable")
        return GeocodingResult(
            longitude=longitude,
            latitude=latitude,
            formatted_address="北京市朝阳区测试路1号",
            province="北京市",
            city="北京市",
            district="朝阳区",
            adcode="110105",
        )


class FakeAddressRepository:
    def __init__(self):
        self.addresses: dict[str, UserAddress] = {}
        self.lock_count = 0

    async def run_in_transaction(self, callback):
        return await callback(object())

    async def acquire_user_address_lock(
        self,
        *,
        user_id,
        session,
    ):
        self.lock_count += 1

    async def count_active(self, *, user_id, session=None):
        return sum(
            1
            for address in self.addresses.values()
            if address.user_id == user_id and not address.is_deleted
        )

    async def create_address(self, address_data, *, session):
        address = UserAddress.model_validate(address_data)
        self.addresses[address.address_id] = address

    async def find_by_id(
        self,
        *,
        user_id,
        address_id,
        session=None,
    ):
        address = self.addresses.get(address_id)
        if (
            address is None
            or address.user_id != user_id
            or address.is_deleted
        ):
            return None
        return address

    async def list_active(self, user_id):
        return sorted(
            [
                address
                for address in self.addresses.values()
                if address.user_id == user_id
                and not address.is_deleted
            ],
            key=lambda address: (
                address.is_default,
                address.update_time,
            ),
            reverse=True,
        )[:15]

    async def update_address(
        self,
        *,
        user_id,
        address_id,
        update_data,
        session,
    ):
        address = await self.find_by_id(
            user_id=user_id,
            address_id=address_id,
            session=session,
        )
        if address is None:
            return None
        updated = address.model_copy(
            update={
                **update_data,
                "version": address.version + 1,
            }
        )
        self.addresses[address_id] = updated
        return updated

    async def clear_default(
        self,
        *,
        user_id,
        update_time,
        session,
    ):
        for address_id, address in list(self.addresses.items()):
            if (
                address.user_id == user_id
                and not address.is_deleted
                and address.is_default
            ):
                self.addresses[address_id] = address.model_copy(
                    update={
                        "is_default": False,
                        "update_time": update_time,
                        "version": address.version + 1,
                    }
                )

    async def set_default(
        self,
        *,
        user_id,
        address_id,
        update_time,
        session,
    ):
        address = await self.find_by_id(
            user_id=user_id,
            address_id=address_id,
            session=session,
        )
        if address is None:
            return False
        self.addresses[address_id] = address.model_copy(
            update={
                "is_default": True,
                "update_time": update_time,
                "version": address.version + 1,
            }
        )
        return True

    async def soft_delete(
        self,
        *,
        user_id,
        address_id,
        update_time,
        session,
    ):
        address = await self.find_by_id(
            user_id=user_id,
            address_id=address_id,
            session=session,
        )
        if address is None:
            return None
        self.addresses[address_id] = address.model_copy(
            update={
                "is_deleted": True,
                "is_default": False,
                "update_time": update_time,
                "version": address.version + 1,
            }
        )
        return address

    async def find_latest_active(self, *, user_id, session):
        addresses = await self.list_active(user_id)
        if not addresses:
            return None
        return max(addresses, key=lambda address: address.update_time)


def make_request(**overrides) -> UserAddressCreate:
    request_data = {
        "receiver_name": "张三",
        "receiver_phone": "13800138000",
        "province": "北京市",
        "city": "北京市",
        "district": "朝阳区",
        "detail_address": "测试路1号",
    }
    request_data.update(overrides)
    return UserAddressCreate(**request_data)


def make_address(
    *,
    address_id: str,
    is_default: bool,
    update_time: datetime,
) -> UserAddress:
    return UserAddress(
        address_id=address_id,
        user_id="user-001",
        receiver_name="张三",
        receiver_phone="13800138000",
        province="北京市",
        city="北京市",
        district="朝阳区",
        detail_address="测试路1号",
        longitude=116.001,
        latitude=39.0,
        formatted_address="北京市朝阳区测试路1号",
        adcode="110105",
        location_source="geocoded",
        verification_status="verified",
        is_default=is_default,
        version=1,
        is_deleted=False,
        create_time=update_time,
        update_time=update_time,
    )


class AddressSchemaTests(unittest.TestCase):
    def test_accepts_mainland_mobile_phone(self):
        self.assertEqual(
            make_request().receiver_phone,
            "13800138000",
        )

    def test_rejects_non_mainland_mobile_phone(self):
        with self.assertRaises(ValidationError):
            make_request(receiver_phone="01012345678")


class AddressServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(
        self,
        *,
        reverse_unavailable: bool = False,
    ):
        repository = FakeAddressRepository()
        amap = FakeAmapService(reverse_unavailable)
        service = AddressService(
            repository,
            DeliveryLocationService(amap),
            now_provider=lambda: TEST_NOW,
        )
        return service, repository, amap

    async def test_first_address_is_automatically_default(self):
        service, repository, _ = self.make_service()

        response = await service.create_address(
            make_request(),
            "user-001",
        )

        self.assertTrue(response.address.is_default)
        self.assertEqual(repository.lock_count, 1)
        self.assertNotIn(
            "user_id",
            response.address.model_dump(),
        )

    async def test_sixteenth_active_address_is_rejected(self):
        service, repository, amap = self.make_service()
        for index in range(15):
            address = make_address(
                address_id=f"address-{index}",
                is_default=index == 0,
                update_time=TEST_NOW,
            )
            repository.addresses[address.address_id] = address

        with self.assertRaises(AddressLimitExceededError):
            await service.create_address(
                make_request(),
                "user-001",
            )
        self.assertEqual(amap.geocode_count, 0)

    async def test_update_unknown_address_does_not_call_amap(self):
        service, _, amap = self.make_service()

        with self.assertRaises(AddressNotFoundError):
            await service.update_address(
                "unknown",
                make_request(),
                "user-001",
            )

        self.assertEqual(amap.geocode_count, 0)

    async def test_setting_default_clears_previous_default(self):
        service, repository, _ = self.make_service()
        repository.addresses = {
            "old": make_address(
                address_id="old",
                is_default=True,
                update_time=TEST_NOW - timedelta(days=1),
            ),
            "new": make_address(
                address_id="new",
                is_default=False,
                update_time=TEST_NOW,
            ),
        }

        response = await service.set_default("new", "user-001")

        self.assertTrue(response.address.is_default)
        self.assertFalse(repository.addresses["old"].is_default)

    async def test_deleting_default_selects_latest_updated_remaining(self):
        service, repository, _ = self.make_service()
        repository.addresses = {
            "default": make_address(
                address_id="default",
                is_default=True,
                update_time=TEST_NOW - timedelta(days=3),
            ),
            "older": make_address(
                address_id="older",
                is_default=False,
                update_time=TEST_NOW - timedelta(days=2),
            ),
            "latest": make_address(
                address_id="latest",
                is_default=False,
                update_time=TEST_NOW - timedelta(days=1),
            ),
        }

        await service.delete_address("default", "user-001")

        self.assertTrue(repository.addresses["default"].is_deleted)
        self.assertTrue(repository.addresses["latest"].is_default)
        self.assertFalse(repository.addresses["older"].is_default)

    async def test_map_pick_can_be_saved_unverified_when_amap_is_down(self):
        service, _, _ = self.make_service(reverse_unavailable=True)

        response = await service.create_address(
            make_request(longitude=116.2, latitude=39.1),
            "user-001",
        )

        self.assertEqual(
            response.address.verification_status,
            "unverified",
        )
        self.assertEqual(response.address.location_source, "map_pick")


if __name__ == "__main__":
    unittest.main()
