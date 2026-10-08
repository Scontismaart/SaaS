"""Shared, value-redacted production network configuration validation."""

import ipaddress
from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse


def _https_origin(value: str) -> str | None:
    try:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in value)
            or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            return None
        port = parsed.port
        return f"https://{parsed.hostname}" + (
            f":{port}" if port not in {None, 443} else ""
        )
    except ValueError:
        return None


def network_config_errors(config: Mapping[str, str | None]) -> list[str]:
    """Validate effective URL fields, never substrings in credentials/fragments."""
    errors = []
    get = lambda name: str(config.get(name) or "").strip()
    try:
        raw_dsn = get("DATABASE_URL")
        dsn = urlparse(raw_dsn)
        modes = parse_qs(dsn.query, keep_blank_values=True).get("sslmode", [])
        if (
            dsn.scheme not in {"postgres", "postgresql"}
            or not dsn.hostname
            or not dsn.path.strip("/")
            or dsn.fragment
            or any(
                marker in raw_dsn.lower()
                for marker in (
                    "<",
                    ">",
                    "placeholder",
                    "user:pass@",
                    "username:password@",
                    "changeme",
                    "replace-me",
                )
            )
            or modes not in [["require"], ["verify-ca"], ["verify-full"]]
        ):
            raise ValueError()
        _ = dsn.port
    except ValueError:
        errors.append("DATABASE_URL: valid PostgreSQL DSN with explicit TLS required")

    public_origin = _https_origin(get("PUBLIC_APP_URL"))
    if public_origin is None:
        errors.append("PUBLIC_APP_URL: explicit HTTPS origin required")
    if _https_origin(get("SUPABASE_URL")) is None:
        errors.append("SUPABASE_URL: explicit HTTPS origin required")
    anon = get("SUPABASE_ANON_KEY").lower()
    if not anon or any(
        marker in anon
        for marker in (
            "<",
            ">",
            "placeholder",
            "changeme",
            "replace-me",
            "your-",
            "xxx",
        )
    ):
        errors.append("SUPABASE_ANON_KEY: missing or placeholder")

    approved = {public_origin} if public_origin else set()
    if public_origin in {"https://melpis.it", "https://app.melpis.it"}:
        approved.update({"https://melpis.it", "https://app.melpis.it"})
    for name in ("CORS_ORIGINS", "CSRF_TRUSTED_ORIGINS"):
        configured = get(name)
        # CSRF uses CORS_ORIGINS when no separate override is supplied.
        if name == "CSRF_TRUSTED_ORIGINS" and not configured:
            continue
        origins = configured.split(",")
        if any(_https_origin(origin.strip()) not in approved for origin in origins):
            errors.append(f"{name}: explicit approved HTTPS origins required")

    try:
        networks = [
            ipaddress.ip_network(value.strip())
            for value in get("TRUSTED_PROXY_CIDRS").split(",")
        ]
        private_ranges = [
            ipaddress.ip_network(value)
            for value in (
                "10.0.0.0/8",
                "172.16.0.0/12",
                "192.168.0.0/16",
                "127.0.0.0/8",
                "fc00::/7",
                "::1/128",
            )
        ]
        if any(
            not any(
                network.version == allowed.version and network.subnet_of(allowed)
                for allowed in private_ranges
            )
            for network in networks
        ):
            raise ValueError()
    except ValueError:
        errors.append("TRUSTED_PROXY_CIDRS: explicit bounded proxy networks required")
    return errors
