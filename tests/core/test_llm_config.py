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