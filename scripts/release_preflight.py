"""Read-only configuration checks for explicit commercial or sandbox releases.

Run with --env-file .env.production; values and secrets are never printed.
Passing this check is not evidence that a cloud account or free quota exists.
"""

import argparse
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values


COMMERCIAL_BOOTSTRAP_PROFILE = "commercial_bootstrap"
SANDBOX_PROFILE = "sandbox"
STRIPE_PRICE_ENV_NAMES = (
    "STRIPE_PRICE_STARTER",
    "STRIPE_PRICE_PRO",
    "STRIPE_PRICE_BUSINESS",
    "STRIPE_PRICE_STARTER_YEARLY",
    "STRIPE_PRICE_PRO_YEARLY",
    "STRIPE_PRICE_BUSINESS_YEARLY",
)
MODEL_ENV_NAMES = (
    "OPENROUTER_MODEL",
    "OPENROUTER_MODEL_CHEAP",
    "OPENROUTER_MODEL_PREMIUM",
    "OPENROUTER_MODEL_FALLBACKS",
    "OPENROUTER_MODEL_INTENT",
)
FREE_MODELS = frozenset(
    {
        "groq/llama-3.1-8b-instant",
        "groq/openai/gpt-oss-20b",
        "groq/openai/gpt-oss-120b",
    }
)
IMAGE_REFERENCE_ENV_NAMES = ("MELPIS_API_IMAGE_REF", "MELPIS_WEB_IMAGE_REF")
_DIGEST_IMAGE_REFERENCE = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+@sha256:[0-9a-f]{64}$"
)
_FQDN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}$"
)
_FINAL_CADDY_HOSTS = frozenset({"melpis.it", "app.melpis.it"})
_PLACEHOLDER_MARKERS = (
    "<",
    ">",
    "xxx",
    "placeholder",
    "your-",
    "your_",
    "changeme",
    "change-me",
    "replace-me",
    "example",
    "dummy",
    "_here",
    "user:pass@",
    "username:password@",
)


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or any(
        marker in normalized for marker in _PLACEHOLDER_MARKERS
    )


def _require(config, errors, name, *, prefix=None, min_length=1):
    value = str(config.get(name) or "").strip()
    if _is_placeholder(value):
        errors.append(f"{name}: missing or placeholder")
    elif prefix is not None and not value.startswith(prefix):
        errors.append(f"{name}: must start with {prefix}")
    elif len(value) < min_length:
        errors.append(f"{name}: invalid format")


def _require_digest_image_reference(config, errors, name):
    value = str(config.get(name) or "").strip()
    if _is_placeholder(value) or not _DIGEST_IMAGE_REFERENCE.fullmatch(value):
        errors.append(f"{name}: must be repository@sha256:<64 lowercase hex>")


def _require_temporary_host(config, errors):
    value = str(config.get("PUBLIC_HOST") or "").strip().lower()
    if _is_placeholder(value):
        errors.append("PUBLIC_HOST: missing or placeholder")
    elif value in _FINAL_CADDY_HOSTS:
        errors.append("PUBLIC_HOST: temporary mode cannot use melpis.it or app.melpis.it")
    elif not _FQDN.fullmatch(value):
        errors.append("PUBLIC_HOST: must be a valid temporary FQDN")


def validate(config):
    errors = []
    profile = str(config.get("LAUNCH_PROFILE") or "").strip().lower()

    required = (
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "ENCRYPTION_KEY",
        "PUBLIC_APP_URL",
        "META_APP_SECRET",
        "META_VERIFY_TOKEN",
    )
    for name in required:
        _require(config, errors, name)
    _require(config, errors, "GROQ_API_KEY", prefix="gsk_", min_length=16)
    for name in IMAGE_REFERENCE_ENV_NAMES:
        _require_digest_image_reference(config, errors, name)

    caddy_site_mode = str(config.get("CADDY_SITE_MODE") or "").strip()
    if caddy_site_mode not in {"temporary", "final"}:
        errors.append("CADDY_SITE_MODE: must be temporary or final")
    elif caddy_site_mode == "temporary":
        _require_temporary_host(config, errors)

    expected = {
        "APP_ENV": "production",
        "LLM_COST_POLICY": "free_only",
        "GROQ_FREE_ACCOUNT_CONFIRMED": "true",
        "GROQ_ZDR_CONFIRMED": "true",
        "AUTH_COOKIE_SECURE": "true",
        "RATE_LIMIT_BACKEND": "redis",
        "GOOGLE_CALENDAR_ENABLED": "false",
        "GOOGLE_BUSINESS_ENABLED": "false",
    }
    for name, expected_value in expected.items():
        if config.get(name) != expected_value:
            errors.append(f"{name}: must be {expected_value}")

    if str(config.get("DEMO_MODE", "")).lower() in {"true", "1", "yes"}:
        errors.append("DEMO_MODE: forbidden")

    if profile == COMMERCIAL_BOOTSTRAP_PROFILE:
        if config.get("SANDBOX_ONLY") != "false":
            errors.append("SANDBOX_ONLY: must be false for commercial_bootstrap")
        _require(config, errors, "STRIPE_SECRET_KEY", prefix="sk_live_", min_length=16)
        _require(
            config, errors, "STRIPE_PUBLISHABLE_KEY", prefix="pk_live_", min_length=16
        )
        _require(
            config, errors, "STRIPE_WEBHOOK_SECRET", prefix="whsec_", min_length=16
        )
        for name in STRIPE_PRICE_ENV_NAMES:
            _require(config, errors, name, prefix="price_", min_length=12)
    elif profile == SANDBOX_PROFILE:
        if config.get("SANDBOX_ONLY") != "true":
            errors.append("SANDBOX_ONLY: must be true for sandbox")
        _require(config, errors, "STRIPE_SECRET_KEY", prefix="sk_test_", min_length=16)
        _require(
            config, errors, "STRIPE_PUBLISHABLE_KEY", prefix="pk_test_", min_length=16
        )
        _require(
            config, errors, "STRIPE_WEBHOOK_SECRET", prefix="whsec_", min_length=16
        )
        _require(config, errors, "WHATSAPP_TEST_RECIPIENTS")
    else:
        errors.append("LAUNCH_PROFILE: must be commercial_bootstrap or sandbox")

    for name in MODEL_ENV_NAMES:
        models = (str(config.get(name) or "")).split(",")
        if any(model.strip() not in FREE_MODELS for model in models if model.strip()):
            errors.append(f"{name}: model outside free allowlist")

    for name in ("PUBLIC_APP_URL", "SUPABASE_URL"):
        parsed = urlparse(config.get(name) or "")
        if parsed.scheme != "https" or not parsed.hostname:
            errors.append(f"{name}: HTTPS required")
    if "sslmode=require" not in (config.get("DATABASE_URL") or ""):
        errors.append("DATABASE_URL: TLS required")

    try:
        from cryptography.fernet import Fernet

        Fernet(config.get("ENCRYPTION_KEY") or "")
    except (ValueError, TypeError):
        errors.append("ENCRYPTION_KEY: invalid Fernet key")

    try:
        networks = [
            ipaddress.ip_network(value.strip())
            for value in (config.get("TRUSTED_PROXY_CIDRS") or "").split(",")
            if value.strip()
        ]
        if not networks or any(network.prefixlen == 0 for network in networks):
            raise ValueError()
    except ValueError:
        errors.append("TRUSTED_PROXY_CIDRS: explicit bounded proxy networks required")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file():
        parser.error("Environment file not found")
    findings = validate(dotenv_values(args.env_file))
    for finding in findings:
        print(f"BLOCK: {finding}")
    print(
        "Configuration blocked"
        if findings
        else "Configuration passes; external release evidence still required"
    )
    raise SystemExit(bool(findings))
