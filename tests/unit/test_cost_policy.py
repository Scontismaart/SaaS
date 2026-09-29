import pytest

from src.core.cost_policy import assert_model_allowed
from src.core.cost_policy import assert_openrouter_catalog_free
import io
import json


@pytest.mark.parametrize("model", ["mistral/mistral-small-latest", "openai/gpt-4o-mini", "openrouter/auto", "cerebras/gpt-oss-120b", "unknown/model"])
def test_zero_budget_rejects_paid_or_unverified_provider(monkeypatch, model):
    monkeypatch.delenv("LLM_COST_POLICY", raising=False)
    monkeypatch.setenv("GROQ_FREE_ACCOUNT_CONFIRMED", "true")
    with pytest.raises(RuntimeError, match="Budget EUR 0"):
        assert_model_allowed(model)


def test_free_account_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setenv("LLM_COST_POLICY", "free_only")
    monkeypatch.delenv("GROQ_FREE_ACCOUNT_CONFIRMED", raising=False)
    with pytest.raises(RuntimeError, match="FREE Groq"):
        assert_model_allowed("groq/openai/gpt-oss-20b")
    monkeypatch.setenv("GROQ_FREE_ACCOUNT_CONFIRMED", "true")
    assert_model_allowed("groq/openai/gpt-oss-20b")


def test_invalid_cost_policy_is_not_paid_opt_in(monkeypatch):
    monkeypatch.setenv("LLM_COST_POLICY", "typo")
    with pytest.raises(RuntimeError, match="non riconosciuta"):
        assert_model_allowed("mistral/mistral-small-latest")


def test_openrouter_catalog_free_model(monkeypatch):
    model = "openrouter/vendor/model:free"
    monkeypatch.setenv("LLM_COST_POLICY", "free_only")
    assert_model_allowed(model)
    payload = {"data": [{"id": "vendor/model:free", "pricing": {"prompt": "0", "completion": "0", "request": "0"}}]}
    monkeypatch.setattr("src.core.cost_policy.urlopen", lambda request, timeout: io.BytesIO(json.dumps(payload).encode()))
    assert_openrouter_catalog_free(model, "dummy-key")


@pytest.mark.parametrize("pricing", [
    {"prompt": "0.1", "completion": "0"},
    {"prompt": "0", "completion": "0", "request": "0.1"},
    {"prompt": "0"},
])
def test_openrouter_catalog_rejects_cost_or_missing_price(monkeypatch, pricing):
    payload = {"data": [{"id": "vendor/model:free", "pricing": pricing}]}
    monkeypatch.setattr("src.core.cost_policy.urlopen", lambda request, timeout: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(RuntimeError, match="non verificabile"):
        assert_openrouter_catalog_free("openrouter/vendor/model:free", "dummy-key")


def test_openrouter_catalog_network_failure_blocks(monkeypatch):
    def unavailable(request, timeout):
        raise OSError("offline")
    monkeypatch.setattr("src.core.cost_policy.urlopen", unavailable)
    with pytest.raises(RuntimeError, match="non verificabile"):
        assert_openrouter_catalog_free("openrouter/vendor/model:free", "dummy-key")
