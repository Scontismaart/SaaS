import ipaddress
import os
from fastapi import Request

def get_client_ip(request: Request) -> ipaddress._BaseAddress | None:
    """Resolve a bounded proxy chain only when the actual socket peer is trusted.

    Run ASGI with proxy-header rewriting disabled. No proxy is trusted by default.
    Malformed chains/configuration return None rather than an allowlisted proxy.
    """
    try:
        peer = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError:
        return None
    try:
        trusted = tuple(ipaddress.ip_network(v.strip(), strict=False) for v in
                        os.getenv("TRUSTED_PROXY_CIDRS", "").split(",") if v.strip())
    except ValueError:
        return None
    if not any(peer in network for network in trusted):
        return peer
    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return peer
    parts = xff.split(",")
    if len(parts) > 32:
        return None
    try:
        chain = [ipaddress.ip_address(part.strip()) for part in parts]
    except ValueError:
        return None
    current = peer
    for address in reversed(chain):
        if not any(current in network for network in trusted):
            break
        current = address
    return current

def is_ip_in_allowed_cidrs(ip: ipaddress._BaseAddress, env_var: str, default_cidrs: tuple[str, ...]) -> bool:
    raw = os.getenv(env_var, ",".join(default_cidrs))
    if not raw.strip():
        return False
    networks = []
    for item in raw.split(","):
        item = item.strip()
        if item:
            try:
                networks.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                return False
    return any(ip in network for network in networks)
