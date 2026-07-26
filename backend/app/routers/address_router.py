from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.dependencies.auth import get_current_user_id
from app.dependencies.database import get_db
from app.dependencies.geocoding import (
    get_delivery_geocoding_rate_limiter,
    get_delivery_location_service,
)
from app.repositories.address_repository import AddressRepository
from app.schemas.address import (
    UserAddressActionResponse,
    UserAddressCreate,
    UserAddressListResponse,
    UserAddressResponse,
    UserAddressUpdate,
)
from app.services.address_service import (
    AddressLimitExceededError,
    AddressNotFoundError,
    AddressService,
)
from app.services.amap_service import AmapServiceUnavailableError
from app.services.delivery_geocoding_rate_limiter import (
    DeliveryGeocodingRateLimitBackendError,
    DeliveryGeocodingRateLimitExceeded,
    DeliveryGeocodingRateLimiter,
)
from app.services.delivery_location_service import (
    AddressNeedsMapPickError,
    DeliveryLocationService,
)


router = APIRouter(prefix="/addresses", tags=["收货地址"])
AddressId = Annotated[
    str,
    Path(min_length=1, max_length=64, description="收货地址ID"),
]


def get_address_repository(db=Depends(get_db)) -> AddressRepository:
    return AddressRepository(db)


def get_address_service(
    repository: AddressRepository = Depends(get_address_repository),
    delivery_location_service: DeliveryLocationService = Depends(
        get_delivery_location_service
    ),
) -> AddressService:
    return AddressService(repository, delivery_location_service)


def _raise_address_error(exc: Exception) -> None:
    if isinstance(exc, AddressNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ADDRESS_NOT_FOUND",
                "message": "收货地址不存在",
            },
        ) from exc
    if isinstance(exc, AddressLimitExceededError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ADDRESS_LIMIT_EXCEEDED",
                "message": "每个用户最多保存15条有效收货地址",
            },
        ) from exc
    if isinstance(exc, AddressNeedsMapPickError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ADDRESS_NEEDS_MAP_PICK",
                "message": "文字地址无法精确定位，请通过地图选点确认",
            },
        ) from exc
    if isinstance(exc, AmapServiceUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "GEOCODING_SERVICE_UNAVAILABLE",
                "message": "地址解析服务暂时不可用",
            },
        ) from exc
    raise exc


async def _check_geocoding_rate_limit(
    limiter: DeliveryGeocodingRateLimiter,
    user_id: str,
) -> None:
    try:
        await limiter.check(user_id)
    except DeliveryGeocodingRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="地址解析请求过于频繁，请稍后重试",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except DeliveryGeocodingRateLimitBackendError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="地址解析限流服务暂时不可用",
        ) from exc


@router.post(
    "",
    response_model=UserAddressResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_address(
    request: UserAddressCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: AddressService = Depends(get_address_service),
    limiter: DeliveryGeocodingRateLimiter = Depends(
        get_delivery_geocoding_rate_limiter
    ),
):
    await _check_geocoding_rate_limit(limiter, user_id)
    try:
        return await service.create_address(request, user_id)
    except (
        AddressLimitExceededError,
        AddressNeedsMapPickError,
        AmapServiceUnavailableError,
    ) as exc:
        _raise_address_error(exc)


@router.get("", response_model=UserAddressListResponse)
async def list_addresses(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: AddressService = Depends(get_address_service),
):
    return await service.list_addresses(user_id)


@router.get("/{address_id}", response_model=UserAddressResponse)
async def get_address(
    address_id: AddressId,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: AddressService = Depends(get_address_service),
):
    try:
        return await service.get_address(address_id, user_id)
    except AddressNotFoundError as exc:
        _raise_address_error(exc)


@router.put("/{address_id}", response_model=UserAddressResponse)
async def update_address(
    address_id: AddressId,
    request: UserAddressUpdate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: AddressService = Depends(get_address_service),
    limiter: DeliveryGeocodingRateLimiter = Depends(
        get_delivery_geocoding_rate_limiter
    ),
):
    await _check_geocoding_rate_limit(limiter, user_id)
    try:
        return await service.update_address(
            address_id,
            request,
            user_id,
        )
    except (
        AddressNotFoundError,
        AddressNeedsMapPickError,
        AmapServiceUnavailableError,
    ) as exc:
        _raise_address_error(exc)


@router.post(
    "/{address_id}/set-default",
    response_model=UserAddressResponse,
)
async def set_default_address(
    address_id: AddressId,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: AddressService = Depends(get_address_service),
):
    try:
        return await service.set_default(address_id, user_id)
    except AddressNotFoundError as exc:
        _raise_address_error(exc)


@router.delete(
    "/{address_id}",
    response_model=UserAddressActionResponse,
)
async def delete_address(
    address_id: AddressId,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: AddressService = Depends(get_address_service),
):
    try:
        return await service.delete_address(address_id, user_id)
    except AddressNotFoundError as exc:
        _raise_address_error(exc)
