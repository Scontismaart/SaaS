"""Restrict service API key usage to internal networks by default."""

from __future__ import annotations

from fastapi import Request

from src.core.auth.trusted_network import get_client_ip, is_ip_in_allowed_cidrs

DEFAULT_ALLOWED_CIDRS = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "fc00::/7",
)

def api_key_request_allowed(request: Request) -> bool:
    if request.client is None:
        return True
    ip = get_client_ip(request)
    if not ip:
        return False
    return is_ip_in_allowed_cidrs(ip, "API_KEY_ALLOWED_CIDRS", DEFAULT_ALLOWED_CIDRS)
