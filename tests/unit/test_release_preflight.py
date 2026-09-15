from cryptography.fernet import Fernet

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("release_preflight", Path("scripts/release_preflight.py"))
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
validate = _MODULE.validate


def valid_config():
    return {
        "APP_ENV": "production", "SANDBOX_ONLY": "true", "LLM_COST_POLICY": "free_only",
        "GROQ_FREE_ACCOUNT_CONFIRMED": "true", "AUTH_COOKIE_SECURE": "true",
        "RATE_LIMIT_BACKEND": "redis", "DATABASE_URL": "postgresql://u:p@db/x?sslmode=require",
        "SUPABASE_URL": "https://project.supabase.co", "SUPABASE_ANON_KEY": "anon-value",
        "ENCRYPTION_KEY": Fernet.generate_key().decode(), "PUBLIC_APP_URL": "https://melpis.it",
        "META_APP_SECRET": "meta-secret", "META_VERIFY_TOKEN": "verify-token",
        "GROQ_API_KEY": "gsk-placeholder-free", "STRIPE_SECRET_KEY": "sk_test_placeholder",
        "STRIPE_WEBHOOK_SECRET": "whsec_placeholder", "WHATSAPP_TEST_RECIPIENTS": "39000000000",
        "TRUSTED_PROXY_CIDRS": "172.30.0.0/24",
        "OPENROUTER_MODEL": "groq/openai/gpt-oss-20b",
        "OPENROUTER_MODEL_CHEAP": "groq/llama-3.1-8b-instant",
        "OPENROUTER_MODEL_PREMIUM": "groq/openai/gpt-oss-20b",
        "OPENROUTER_MODEL_FALLBACKS": "groq/llama-3.1-8b-instant,groq/openai/gpt-oss-120b",
    }


def test_valid_zero_cost_sandbox_configuration_passes():
    assert validate(valid_config()) == []


def test_paid_or_unbounded_configuration_is_blocked():
    config = valid_config()
    config.update({"SANDBOX_ONLY": "false", "STRIPE_SECRET_KEY": "sk_live_no",
                   "OPENROUTER_MODEL": "openai/gpt-4o", "TRUSTED_PROXY_CIDRS": "0.0.0.0/0"})
    findings = "\n".join(validate(config))
    assert "SANDBOX_ONLY" in findings
    assert "test key required" in findings
    assert "outside free allowlist" in findings
    assert "bounded proxy" in findings
