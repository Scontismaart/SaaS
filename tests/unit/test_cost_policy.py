import pytest

from src.core.cost_policy import assert_model_allowed


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
