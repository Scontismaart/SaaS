from unittest.mock import MagicMock, patch

import pytest

from src.core.llm_routing import LLMRoute


def test_review_runner_disables_unaccounted_automatic_fallback():
    from src.core.crew_runner_review import genera_risposta_recensione

    crew = MagicMock()
    crew.usage_metrics = None
    crew.kickoff.side_effect = RuntimeError("provider failure")
    usage = {"attempts": []}
    with patch("src.core.crew_runner_review.route_llm", return_value=LLMRoute(
        model="groq/model-primary", tier="premium", reason="review",
        fallback_models=("groq/model-fallback",),
    )), patch("src.core.crew_runner_review.crea_review_crew", return_value=crew) as make_crew:
        with pytest.raises(RuntimeError, match="Tutti i modelli configurati hanno fallito"):
            genera_risposta_recensione("review", usage_sink=usage)

    assert make_crew.call_count == 1
    assert usage["attempts"] == [{
        "model": "groq/model-primary", "reason": "review",
        "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
        "latency_ms": usage["attempts"][0]["latency_ms"], "fallback": False,
    }]
