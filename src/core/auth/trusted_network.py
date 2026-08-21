import ipaddress
import os
from fastapi import Request

def get_client_ip(request: Request) -> ipaddress._BaseAddress | None:
    """
    Extracts the true client IP from the request.
    Under a reverse proxy (like Traefik in Coolify), the client IP is appended
    to X-Forwarded-For. Thus, the last IP in the X-Forwarded-For list is the 
    address that connected to the proxy.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # The right-most IP is appended by the proxy we are directly behind.
        # This prevents an attacker from spoofing by sending X-Forwarded-For: 127.0.0.1
        # which would result in X-Forwarded-For: 127.0.0.1, <true_attacker_ip>
        ip_str = xff.split(",")[-1].strip()
    else:
        ip_str = request.client.host if request.client else ""
        
    try:
        return ipaddress.ip_address(ip_str)
    except ValueError:
        return None

def is_ip_in_allowed_cidrs(ip: ipaddress._BaseAddress, env_var: str, default_cidrs: tuple[str, ...]) -> bool:
    raw = os.getenv(env_var, ",".join(default_cidrs))
    if not raw.strip():
        return False
    networks = []
    for item in raw.split(","):
        item = item.strip()
        if item:
            networks.append(ipaddress.ip_network(item, strict=False))
    return any(ip in network for network in networks)
