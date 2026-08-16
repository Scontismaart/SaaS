"""A/B test dei prompt per tenant (task 12): assegnazione deterministica
per org (stabile, senza storage), varianti definite in codice e attivabili
via env, logging della variante negli usage events."""

from src.agents.prompts import (
    assegna_variante,
    costruisci_system_prompt,
    varianti_attive,
)
from src.models.schemas import ProfiloAttivita


def _profilo():
    return ProfiloAttivita(
        nome="Trattoria Da Mario",
        tipo_attivita="ristorante",
        tono="cordiale",
        orari="Lun-Ven 12-15",
        servizi_principali=["Cucina tipica"],
        note_speciali=["Allergie allo staff"],
    )


class TestVariantiAttive:
    def test_default_solo_control(self):
        import os
        os.environ.pop("GUARDRAIL_AB_VARIANTS", None)
        assert varianti_attive() == ["control"]

    def test_env_attiva_varianti(self, monkeypatch):
        monkeypatch.setenv("GUARDRAIL_AB_VARIANTS", "control,concise")
        assert varianti_attive() == ["control", "concise"]

    def test_varianti_sconosciute_scartate(self, monkeypatch):
        monkeypatch.setenv("GUARDRAIL_AB_VARIANTS", "control,boh,concise")
        assert varianti_attive() == ["control", "concise"]

    def test_control_sempre_presente(self, monkeypatch):
        monkeypatch.setenv("GUARDRAIL_AB_VARIANTS", "concise")
        assert varianti_attive() == ["control", "concise"]


class TestAssegnazione:
    def test_deterministica_per_org(self, monkeypatch):
        monkeypatch.setenv("GUARDRAIL_AB_VARIANTS", "control,concise")
        org_id = "9b2f1c4a-1111-2222-3333-444455556666"
        assert assegna_variante(org_id) == assegna_variante(org_id)

    def test_valore_sempre_valido(self, monkeypatch):
        monkeypatch.setenv("GUARDRAIL_AB_VARIANTS", "control,concise")
        for i in range(50):
            assert assegna_variante(f"org-{i}") in {"control", "concise"}

    def test_solo_control_torna_sempre_control(self, monkeypatch):
        monkeypatch.setenv("GUARDRAIL_AB_VARIANTS", "control")
        for i in range(10):
            assert assegna_variante(f"org-{i}") == "control"

    def test_distribuzione_non_degenere(self, monkeypatch):
        """Con due varianti attive, 100 org non devono finire TUTTE sulla
        stessa (sarebbe un A/B inutile). Check volutamente lasco."""
        monkeypatch.setenv("GUARDRAIL_AB_VARIANTS", "control,concise")
        assegnate = {assegna_variante(f"org-{i}") for i in range(100)}
        assert assegnate == {"control", "concise"}


class TestPromptConVariante:
    def test_control_prompt_invariato(self):
        base = costruisci_system_prompt(_profilo())
        con_variante = costruisci_system_prompt(_profilo(), variante="control")
        assert base == con_variante

    def test_concise_aggiunge_istruzioni(self):
        base = costruisci_system_prompt(_profilo())
        concise = costruisci_system_prompt(_profilo(), variante="concise")
        assert len(concise) > len(base)
        # la variante aggiunge, non sostituisce: le regole base restano
        assert "REGOLE DI ESCALATION" in concise
        assert "concisa" in concise.lower() or "breve" in concise.lower()
