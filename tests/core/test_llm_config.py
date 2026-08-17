import pytest

from src.core.llm_config import MODELLO_DEFAULT, crea_llm
from src.core.llm_routing import LLMRouteRequest


def test_crea_llm_inietta_sempre_data_collection_deny(monkeypatch):
    """Ogni chiamata deve negare l'uso dei dati per training su OpenRouter
    (extra_body provider.data_collection='deny'), incluso il futuro."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    llm = crea_llm(model="acme/modello")

    extra_body = llm.additional_params["extra_body"]
    assert extra_body["provider"]["data_collection"] == "deny"


def test_crea_llm_usa_modello_da_route_request(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "cheap/model")
    monkeypatch.setenv("OPENROUTER_MODEL_PREMIUM", "premium/model")

    llm = crea_llm(route_request=LLMRouteRequest(task_type="review"))

    assert llm.model == "premium/model"


def test_crea_llm_senza_route_usa_default_non_free(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    llm = crea_llm()

    assert llm.model == MODELLO_DEFAULT
    assert not llm.model.endswith(":free")


def test_modello_default_e_un_modello_paid():
    """Il 'vero ultimo fallback' non deve essere un endpoint free che
    addestra sui dati dei clienti."""
    assert MODELLO_DEFAULT == "openai/gpt-4o-mini"


def test_crea_llm_groq_pass_through_senza_deny(monkeypatch):
    """Il fallback Groq passa per LiteLLM, usa la sua chiave e NON deve
    ricevere il parametro OpenRouter-specifico data_collection (Groq non
    addestra sui dati per policy)."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    llm = crea_llm(model="groq/llama-3.3-70b-versatile")

    assert llm.is_litellm is True
    assert llm.model == "groq/llama-3.3-70b-versatile"
    assert "extra_body" not in llm.additional_params


def test_crea_llm_cerebras_pass_through_senza_deny(monkeypatch):
    """Il fallback Cerebras è un provider nativo di CrewAI con base_url
    dedicato e la sua chiave; niente parametro OpenRouter."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-test")

    llm = crea_llm(model="cerebras/llama-3.3-70b")

    assert llm.base_url == "https://api.cerebras.ai/v1"
    assert llm.model == "llama-3.3-70b"
    assert "extra_body" not in llm.additional_params


def test_crea_llm_richiede_la_chiave_del_provider(monkeypatch):
    """Senza GROQ_API_KEY il path Groq deve fallire con errore esplicito,
    non silenziosamente usare la chiave OpenRouter."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        crea_llm(model="groq/llama-3.3-70b-versatile")