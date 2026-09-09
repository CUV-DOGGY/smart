import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from app.ports.repositories import AddressRepositoryPort
from app.schemas.address import (
    UserAddress,
    UserAddressActionResponse,
    UserAddressCreate,
    UserAddressData,
    UserAddressListResponse,
    UserAddressResponse,
    UserAddressUpdate,
)
from app.schemas.delivery import ResolvedDeliveryLocation
from app.services.delivery_location_service import DeliveryLocationService

MAXIMUM_ADDRESSES_PER_USER = 15


class AddressNotFoundError(RuntimeError):
    """地址不存在、已删除或不属于当前用户。"""


class AddressLimitExceededError(RuntimeError):
    """当前用户的有效收货地址数量已达到上限。"""


class AddressService:
    def __init__(
        self,
        repository: AddressRepositoryPort,
        delivery_location_service: DeliveryLocationService,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.delivery_location_service = delivery_location_service
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def create_address(
        self,
        request: UserAddressCreate,
        user_id: str,
    ) -> UserAddressResponse:
        if (
            await self.repository.count_active(user_id=user_id)
            >= MAXIMUM_ADDRESSES_PER_USER
        ):
            raise AddressLimitExceededError("The user already has 15 active addresses")

        resolved = await self.delivery_location_service.resolve(request)
        current_time = self._current_time()
        address_id = str(uuid.uuid4())

        async def create_in_transaction(session):
            await self.repository.acquire_user_address_lock(
                user_id=user_id,
                session=session,
            )
            active_count = await self.repository.count_active(
                user_id=user_id,
                session=session,
            )
            if active_count >= MAXIMUM_ADDRESSES_PER_USER:
                raise AddressLimitExceededError(
                    "The user already has 15 active addresses"
                )

            address = UserAddress(
                address_id=address_id,
                user_id=user_id,
                receiver_name=request.receiver_name,
                receiver_phone=request.receiver_phone,
                **self._location_fields(request, resolved),
                is_default=active_count == 0,
                version=1,
                is_deleted=False,
                create_time=current_time,
                update_time=current_time,
            )
            await self.repository.create_address(
                address.model_dump(),
                session=session,
            )
            return address

        address = await self.repository.run_in_transaction(create_in_transaction)
        return UserAddressResponse(
            status="success",
            message="Address created successfully",
            address=UserAddressData.from_document(address),
        )

    async def get_address(
        self,
        address_id: str,
        user_id: str,
    ) -> UserAddressResponse:
        address = await self.repository.find_by_id(
            user_id=user_id,
            address_id=address_id,
        )
        if address is None:
            raise AddressNotFoundError("Address not found")
        return UserAddressResponse(
            status="success",
            message="Address queried successfully",
            address=UserAddressData.from_document(address),
        )

    async def list_addresses(
        self,
        user_id: str,
    ) -> UserAddressListResponse:
        addresses = await self.repository.list_active(user_id)
        return UserAddressListResponse(
            status="success",
            message="Addresses queried successfully",
            addresses=[UserAddressData.from_document(address) for address in addresses],
        )

    async def update_address(
        self,
        address_id: str,
        request: UserAddressUpdate,
        user_id: str,
    ) -> UserAddressResponse:
        existing = await self.repository.find_by_id(
            user_id=user_id,
            address_id=address_id,
        )
        if existing is None:
            raise AddressNotFoundError("Address not found")

        resolved = await self.delivery_location_service.resolve(request)
        current_time = self._current_time()
        update_data = {
            "receiver_name": request.receiver_name,
            "receiver_phone": request.receiver_phone,
            **self._location_fields(request, resolved),
            "update_time": current_time,
        }

        async def update_in_transaction(session):
            await self.repository.acquire_user_address_lock(
                user_id=user_id,
                session=session,
            )
            address = await self.repository.update_address(
                user_id=user_id,
                address_id=address_id,
                update_data=update_data,
                session=session,
            )
            if address is None:
                raise AddressNotFoundError("Address not found")
            return address

        address = await self.repository.run_in_transaction(update_in_transaction)
        return UserAddressResponse(
            status="success",
            message="Address updated successfully",
            address=UserAddressData.from_document(address),
        )

    async def set_default(
        self,
        address_id: str,
        user_id: str,
        *,
        session=None,
    ) -> UserAddressResponse:
        current_time = self._current_time()

        async def set_default_in_transaction(session):
            await self.repository.acquire_user_address_lock(
                user_id=user_id,
                session=session,
            )
            target = await self.repository.find_by_id(
                user_id=user_id,
                address_id=address_id,
                session=session,
            )
            if target is None:
                raise AddressNotFoundError("Address not found")
            if target.is_default:
                return target

            await self.repository.clear_default(
                user_id=user_id,
                update_time=current_time,
                session=session,
            )
            updated = await self.repository.set_default(
                user_id=user_id,
                address_id=address_id,
                update_time=current_time,
                session=session,
            )
            if not updated:
                raise AddressNotFoundError("Address not found")
            result = await self.repository.find_by_id(
                user_id=user_id,
                address_id=address_id,
                session=session,
            )
            if result is None:
                raise AddressNotFoundError("Address not found")
            return result

        if session is None:
            address = await self.repository.run_in_transaction(
                set_default_in_transaction
            )
        else:
            address = await set_default_in_transaction(session)
        return UserAddressResponse(
            status="success",
            message="Default address updated successfully",
            address=UserAddressData.from_document(address),
        )

    async def delete_address(
        self,
        address_id: str,
        user_id: str,
        *,
        session=None,
    ) -> UserAddressActionResponse:
        current_time = self._current_time()

        async def delete_in_transaction(session):
            await self.repository.acquire_user_address_lock(
                user_id=user_id,
                session=session,
            )
            deleted = await self.repository.soft_delete(
                user_id=user_id,
                address_id=address_id,
                update_time=current_time,
                session=session,
            )
            if deleted is None:
                raise AddressNotFoundError("Address not found")

            if deleted.is_default:
                replacement = await self.repository.find_latest_active(
                    user_id=user_id,
                    session=session,
                )
                if replacement is not None:
                    await self.repository.set_default(
                        user_id=user_id,
                        address_id=replacement.address_id,
                        update_time=current_time,
                        session=session,
                    )

        if session is None:
            await self.repository.run_in_transaction(delete_in_transaction)
        else:
            await delete_in_transaction(session)
        return UserAddressActionResponse(
            status="success",
            message="Address deleted successfully",
        )

    @staticmethod
    def _location_fields(
        request: UserAddressCreate,
        resolved: ResolvedDeliveryLocation,
    ) -> dict:
        return {
            "province": resolved.province or request.province,
            "city": resolved.city or request.city,
            "district": resolved.district or request.district,
            "detail_address": request.detail_address,
            "longitude": resolved.longitude,
            "latitude": resolved.latitude,
            "formatted_address": resolved.formatted_address,
            "adcode": resolved.adcode,
            "location_source": resolved.location_source,
            "verification_status": resolved.verification_status,
        }

    def _current_time(self) -> datetime:
        current_time = self.now_provider()
        if current_time.tzinfo is None:
            raise RuntimeError("now_provider must return a timezone-aware datetime")
        return current_time.astimezone(timezone.utc)
