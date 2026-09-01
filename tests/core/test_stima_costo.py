from src.core.llm_routing import stima_costo_eur


def test_stima_modello_noto():
    costo = stima_costo_eur("openai/mistral-small", 1_000_000, 1_000_000)
    assert costo == 0.2 + 0.6  # prezzi tabellati per 1M


def test_stima_modello_sconosciuto_none():
    assert stima_costo_eur("modello-marziano", 100, 100) is None


def test_stima_token_mancanti_none():
    assert stima_costo_eur("openai/mistral-small", None, 10) is None


def test_stima_prefisso_provider_opzionale():
    assert stima_costo_eur("mistral-small", 1_000_000, 0) == 0.2


def test_stima_modelli_default_di_routing():
    from src.core.llm_routing import (
        _DEFAULT_CHEAP_MODEL,
        _DEFAULT_PREMIUM_MODEL,
        _DEFAULT_FALLBACK_MODELS,
    )
    modelli = [_DEFAULT_CHEAP_MODEL, _DEFAULT_PREMIUM_MODEL]
    modelli += [m for m in _DEFAULT_FALLBACK_MODELS.split(",") if m.strip()]
    for model in modelli:
        assert stima_costo_eur(model, 1000, 1000) is not None, \
            f"modello di default senza prezzo: {model}"
