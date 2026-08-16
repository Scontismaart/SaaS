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


def test_intent_faq_forza_cheap_anche_senza_keyword(monkeypatch):
    """Task 12: il classificatore di intent dice 'faq' per un testo senza
    keyword (es. 'me lo ripeti?') -> tier economico con reason esplicito."""
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    route = route_llm(
        LLMRouteRequest(
            task_type="customer_message",
            user_text="me lo ripeti per favore",
            remaining_budget_ratio=0.8,
            intent="faq",
        )
    )

    assert route.tier == "cheap"
    assert route.model == "cheap/model"
    assert route.reason == "intent_classified"


def test_intent_booking_e_complaint_forzano_premium(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    for intent in ("booking", "complaint", "out_of_scope"):
        route = route_llm(
            LLMRouteRequest(
                task_type="customer_message",
                user_text="una frase qualunque",
                remaining_budget_ratio=0.8,
                intent=intent,
            )
        )
        assert route.tier == "premium"
        assert route.reason == "intent_classified"


def test_intent_chitchat_forza_cheap(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    route = route_llm(
        LLMRouteRequest(
            task_type="customer_message",
            user_text="una frase qualunque",
            remaining_budget_ratio=0.8,
            intent="chitchat",
        )
    )
    assert route.tier == "cheap"
    assert route.reason == "intent_classified"


def test_intent_vince_sulle_keyword_ma_non_su_budget_e_force(monkeypatch):
    """Precedenza: force_tier > budget_low > task_type premium > intent >
    keyword. Il budget basso resta il tetto: anche una FAQ va sul cheap."""
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    low_budget = route_llm(
        LLMRouteRequest(
            task_type="customer_message",
            user_text="A che ora aprite?",
            remaining_budget_ratio=0.02,
            intent="booking",
        )
    )
    assert low_budget.reason == "budget_low"

    forced = route_llm(
        LLMRouteRequest(
            task_type="customer_message",
            user_text="A che ora aprite?",
            force_tier="premium",
            intent="faq",
        )
    )
    assert forced.reason == "forced_premium"


def test_intent_assente_comportamento_keyword_invariato(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    route = route_llm(
        LLMRouteRequest(
            task_type="customer_message",
            user_text="A che ora aprite?",
            remaining_budget_ratio=0.8,
        )
    )
    assert route.reason == "simple_faq"
