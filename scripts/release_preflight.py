"""Read-only configuration checks for the zero-cost SANDBOX release.

Run with --env-file .env.staging; values/secrets are never printed.
Passing this check is not evidence that a cloud account or free quota exists.
"""
import argparse
import ipaddress
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values


def validate(config):
    errors = []
    required = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_ANON_KEY", "ENCRYPTION_KEY",
                "PUBLIC_APP_URL", "META_APP_SECRET", "META_VERIFY_TOKEN", "GROQ_API_KEY",
                "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "WHATSAPP_TEST_RECIPIENTS")
    for name in required:
        value = config.get(name) or ""
        if not value or any(marker in value for marker in ("<", ">", "xxx", "your-")):
            errors.append(f"{name}: missing or placeholder")
    for name, expected in {"APP_ENV": "production", "SANDBOX_ONLY": "true",
                           "LLM_COST_POLICY": "free_only", "GROQ_FREE_ACCOUNT_CONFIRMED": "true",
                           "AUTH_COOKIE_SECURE": "true", "RATE_LIMIT_BACKEND": "redis"}.items():
        if config.get(name) != expected:
            errors.append(f"{name}: must be {expected}")
    if str(config.get("DEMO_MODE", "")).lower() in {"true", "1", "yes"}:
        errors.append("DEMO_MODE: forbidden")
    if not (config.get("STRIPE_SECRET_KEY") or "").startswith("sk_test_"):
        errors.append("STRIPE_SECRET_KEY: test key required")
    allowed = {"groq/llama-3.1-8b-instant", "groq/openai/gpt-oss-20b", "groq/openai/gpt-oss-120b"}
    for name in ("OPENROUTER_MODEL", "OPENROUTER_MODEL_CHEAP", "OPENROUTER_MODEL_PREMIUM",
                 "OPENROUTER_MODEL_FALLBACKS", "OPENROUTER_MODEL_INTENT"):
        if any(model.strip() not in allowed for model in (config.get(name) or "").split(",") if model.strip()):
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
        networks = [ipaddress.ip_network(v.strip()) for v in (config.get("TRUSTED_PROXY_CIDRS") or "").split(",") if v.strip()]
        if not networks or any(n.prefixlen == 0 for n in networks):
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
    print("Configuration blocked" if findings else "Configuration passes; external release evidence still required")
    raise SystemExit(bool(findings))
