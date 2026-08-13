from src.core.llm_config import (
    LLMRouteRequest,
    budget_ratio_from_billing,
    get_route_fallback_models,
    route_llm,
)


def test_simple_faq_uses_cheap_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    route = route_llm(
        LLMRouteRequest(
            task_type="customer_message",
            user_text="A che ora aprite?",
            remaining_budget_ratio=0.8,
        )
    )

    assert route.tier == "cheap"
    assert route.model == "cheap/model"
    assert route.reason == "simple_faq"


def test_review_uses_premium_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    route = route_llm(
        LLMRouteRequest(
            task_type="review",
            user_text="Recensione negativa molto articolata",
            remaining_budget_ratio=0.9,
        )
    )

    assert route.tier == "premium"
    assert route.model == "premium/model"
    assert route.reason == "premium_task"


def test_low_budget_downgrades_to_cheap_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    route = route_llm(
        LLMRouteRequest(
            task_type="review",
            user_text="Recensione complessa",
            remaining_budget_ratio=0.02,
        )
    )

    assert route.tier == "cheap"
    assert route.model == "cheap/model"
    assert route.reason == "budget_low"


def test_escalation_keywords_use_premium_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    route = route_llm(
        LLMRouteRequest(
            task_type="customer_message",
            user_text="Sono arrabbiato, voglio parlare con un responsabile",
            remaining_budget_ratio=0.7,
        )
    )

    assert route.tier == "premium"
    assert route.reason == "complex_or_escalation"


def test_fallback_models_keep_order_and_skip_primary(monkeypatch):
    monkeypatch.setenv(
        "OPENROUTER_MODEL_FALLBACKS",
        "cheap/model, fallback/one, fallback/two, fallback/one",
    )

    fallbacks = get_route_fallback_models("cheap/model")

    assert fallbacks == ["fallback/one", "fallback/two"]


def test_budget_ratio_from_billing_snapshot():
    ratio = budget_ratio_from_billing({
        "messages_used_this_period": 90,
        "messages_limit": 100,
    })

    assert ratio == 0.1
