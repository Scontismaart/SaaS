from types import SimpleNamespace

import pytest

import src.core.crew_runner as crew_runner
from src.models.schemas import MessaggioInput, ProfiloAttivita, RispostaOutput


class FakeCrew:
    def __init__(self, con_metrics=True):
        if con_metrics:
            self.usage_metrics = SimpleNamespace(
                prompt_tokens=100, completion_tokens=50, total_tokens=150,
            )

    async def kickoff_async(self):
        return SimpleNamespace(
            pydantic=RispostaOutput(risposta="ciao", richiede_umano=False, motivo="ok")
        )


def _profilo():
    return ProfiloAttivita(nome="Test", tipo_attivita="ristorante", tono="cordiale", orari="9-18")


@pytest.mark.asyncio
async def test_sink_riempito_con_metriche_reali(monkeypatch):
    def fake_crea_crew(*args, **kwargs):
        return FakeCrew()
    monkeypatch.setattr(crew_runner, "crea_crew", fake_crea_crew)
    monkeypatch.setattr(crew_runner, "route_llm",
                        lambda req: SimpleNamespace(model="modello-test", fallback_models=[],
                                                    tier="premium", reason="test"))
    monkeypatch.setattr(crew_runner, "_route_request_for_message", lambda *a, **k: None)

    sink = {}
    out = await crew_runner.genera_risposta_async(
        MessaggioInput(testo="ciao"), _profilo(), usage_sink=sink,
    )
    assert out.risposta == "ciao"
    assert sink["model_effettivo"] == "modello-test"
    assert sink["fallback_usato"] is False
    assert sink["prompt_tokens"] == 100 and sink["completion_tokens"] == 50
    assert sink["total_tokens"] == 150
    assert sink["latenza_ms"] >= 0


@pytest.mark.asyncio
async def test_sink_segna_fallback_e_metrice_mancanti(monkeypatch):
    def fake_crea_crew(*args, **kwargs):
        if kwargs.get("model") == "modello-test":
            raise RuntimeError("down")
        return FakeCrew(con_metrics=False)  # senza usage_metrics
    monkeypatch.setattr(crew_runner, "crea_crew", fake_crea_crew)
    monkeypatch.setattr(crew_runner, "route_llm",
                        lambda req: SimpleNamespace(model="modello-test",
                                                    fallback_models=["modello-fallback"],
                                                    tier="premium", reason="test"))
    monkeypatch.setattr(crew_runner, "_route_request_for_message", lambda *a, **k: None)

    sink = {}
    await crew_runner.genera_risposta_async(MessaggioInput(testo="ciao"), _profilo(), usage_sink=sink)
    assert sink["model_effettivo"] == "modello-fallback"
    assert sink["fallback_usato"] is True
    assert sink["prompt_tokens"] is None
