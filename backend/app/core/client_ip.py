import ipaddress
from collections.abc import Sequence

from fastapi import Request


def _is_trusted_proxy(address: str, trusted_proxy_cidrs: Sequence[str]) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    for cidr in trusted_proxy_cidrs:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(
    request: Request,
    trusted_proxy_cidrs: Sequence[str],
) -> str:
    """
    默认使用直连 IP。仅当直连方是可信代理时，才从 X-Forwarded-For
    右向左跳过可信代理，取得第一个不可信地址作为客户端 IP。
    """
    peer_ip = request.client.host if request.client is not None else "unknown"
    if not trusted_proxy_cidrs or not _is_trusted_proxy(
        peer_ip,
        trusted_proxy_cidrs,
    ):
        return peer_ip

    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return peer_ip

    chain = [item.strip() for item in forwarded_for.split(",") if item.strip()]
    chain.append(peer_ip)
    for candidate in reversed(chain):
        if not _is_trusted_proxy(candidate, trusted_proxy_cidrs):
            try:
                return ipaddress.ip_address(candidate).compressed
            except ValueError:
                return peer_ip
    return peer_ip
