import importlib.util
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values


_SPEC = importlib.util.spec_from_file_location(
    "release_preflight", Path("scripts/release_preflight.py")
)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
validate = _MODULE.validate
STRIPE_PRICE_ENV_NAMES = _MODULE.STRIPE_PRICE_ENV_NAMES


def test_production_example_declares_safe_commercial_defaults():
    config = dotenv_values(".env.production.example")
    assert config["LAUNCH_PROFILE"] == "commercial_bootstrap"
    assert config["SANDBOX_ONLY"] == "false"
    assert config["GROQ_FREE_ACCOUNT_CONFIRMED"] == "false"
    assert config["GROQ_ZDR_CONFIRMED"] == "false"
    assert config["GOOGLE_CALENDAR_ENABLED"] == "false"
    assert config["GOOGLE_BUSINESS_ENABLED"] == "false"
    assert validate(config)


def test_general_example_is_an_explicit_disabled_sandbox():
    config = dotenv_values(".env.example")
    assert config["LAUNCH_PROFILE"] == "sandbox"
    assert config["SANDBOX_ONLY"] == "true"
    assert config["GOOGLE_CALENDAR_ENABLED"] == "false"
    assert config["GOOGLE_BUSINESS_ENABLED"] == "false"


def common_config():
    return {
        "APP_ENV": "production",
        "LLM_COST_POLICY": "free_only",
        "GROQ_FREE_ACCOUNT_CONFIRMED": "true",
        "GROQ_ZDR_CONFIRMED": "true",
        "AUTH_COOKIE_SECURE": "true",
        "RATE_LIMIT_BACKEND": "redis",
        "GOOGLE_CALENDAR_ENABLED": "false",
        "GOOGLE_BUSINESS_ENABLED": "false",
        "DATABASE_URL": "postgresql://u:p@db/x?sslmode=require",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_ANON_KEY": "anon-unit-safe-value",
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "PUBLIC_APP_URL": "https://melpis.it",
        "META_APP_SECRET": "meta-unit-safe-value",
        "META_VERIFY_TOKEN": "verify-unit-safe-value",
        "GROQ_API_KEY": "gsk_unit_safe_value",
        "STRIPE_WEBHOOK_SECRET": "whsec_unit_safe_value",
        "TRUSTED_PROXY_CIDRS": "172.30.0.0/24",
        "OPENROUTER_MODEL": "groq/openai/gpt-oss-20b",
        "OPENROUTER_MODEL_CHEAP": "groq/llama-3.1-8b-instant",
        "OPENROUTER_MODEL_PREMIUM": "groq/openai/gpt-oss-20b",
        "OPENROUTER_MODEL_FALLBACKS": (
            "groq/llama-3.1-8b-instant,groq/openai/gpt-oss-120b"
        ),
    }


def commercial_config():
    config = common_config()
    config.update(
        {
            "LAUNCH_PROFILE": "commercial_bootstrap",
            "SANDBOX_ONLY": "false",
            "STRIPE_SECRET_KEY": "sk_live_unit_safe_value",
            "STRIPE_PUBLISHABLE_KEY": "pk_live_unit_safe_value",
        }
    )
    config.update(
        {name: f"price_live_{name.lower()}" for name in STRIPE_PRICE_ENV_NAMES}
    )
    return config


def sandbox_config():
    config = common_config()
    config.update(
        {
            "LAUNCH_PROFILE": "sandbox",
            "SANDBOX_ONLY": "true",
            "STRIPE_SECRET_KEY": "sk_test_unit_safe_value",
            "STRIPE_PUBLISHABLE_KEY": "pk_test_unit_safe_value",
            "WHATSAPP_TEST_RECIPIENTS": "39000000000",
        }
    )
    return config


def test_valid_commercial_bootstrap_configuration_passes():
    assert validate(commercial_config()) == []


def test_valid_sandbox_configuration_passes():
    assert validate(sandbox_config()) == []


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("STRIPE_SECRET_KEY", "sk_test_unit_safe_value"),
        ("STRIPE_PUBLISHABLE_KEY", "pk_test_unit_safe_value"),
    ),
)
def test_commercial_bootstrap_blocks_mixed_stripe_modes(name, value):
    config = commercial_config()
    config[name] = value
    assert any(name in finding for finding in validate(config))


def test_sandbox_blocks_live_stripe_credentials():
    config = sandbox_config()
    config["STRIPE_SECRET_KEY"] = "sk_live_unit_safe_value"
    assert any("STRIPE_SECRET_KEY" in finding for finding in validate(config))


@pytest.mark.parametrize("name", STRIPE_PRICE_ENV_NAMES)
def test_commercial_bootstrap_requires_all_six_live_prices(name):
    config = commercial_config()
    del config[name]
    assert f"{name}: missing or placeholder" in validate(config)


@pytest.mark.parametrize("name", ("GROQ_FREE_ACCOUNT_CONFIRMED", "GROQ_ZDR_CONFIRMED"))
def test_profiles_require_groq_free_and_zdr_confirmations(name):
    config = commercial_config()
    config[name] = "false"
    assert f"{name}: must be true" in validate(config)


def test_paid_ai_policy_is_blocked():
    config = commercial_config()
    config["LLM_COST_POLICY"] = "standard"
    assert "LLM_COST_POLICY: must be free_only" in validate(config)


def test_non_allowlisted_model_is_blocked():
    config = commercial_config()
    config["OPENROUTER_MODEL"] = "openai/gpt-4o"
    assert "OPENROUTER_MODEL: model outside free allowlist" in validate(config)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("GROQ_API_KEY", "gsk_placeholder"),
        ("STRIPE_SECRET_KEY", "sk_live_replace-me"),
        ("STRIPE_WEBHOOK_SECRET", "whsec_xxx"),
    ),
)
def test_placeholder_shaped_production_secrets_are_blocked(name, value):
    config = commercial_config()
    config[name] = value
    assert f"{name}: missing or placeholder" in validate(config)


def test_short_placeholder_key_is_blocked():
    config = commercial_config()
    config["STRIPE_SECRET_KEY"] = "sk_live_no"
    assert "STRIPE_SECRET_KEY: invalid format" in validate(config)


def test_placeholder_database_credentials_are_blocked():
    config = commercial_config()
    config["DATABASE_URL"] = "postgresql://user:pass@host/db?sslmode=require"
    assert "DATABASE_URL: missing or placeholder" in validate(config)


@pytest.mark.parametrize("name", ("GOOGLE_CALENDAR_ENABLED", "GOOGLE_BUSINESS_ENABLED"))
def test_google_integrations_must_be_explicitly_disabled(name):
    config = commercial_config()
    config[name] = "true"
    assert f"{name}: must be false" in validate(config)


def test_unknown_or_implicit_profile_is_blocked():
    config = commercial_config()
    del config["LAUNCH_PROFILE"]
    assert any("LAUNCH_PROFILE" in finding for finding in validate(config))


def test_unbounded_proxy_configuration_is_blocked():
    config = commercial_config()
    config["TRUSTED_PROXY_CIDRS"] = "0.0.0.0/0"
    assert any("bounded proxy" in finding for finding in validate(config))
