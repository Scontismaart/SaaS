"""Multilingua (task 14): blocco LINGUE nel system prompt del responder.

Rilevamento lingua delegato al LLM (nessuna libreria); policy sulle lingue
non supportate: best-effort per tutti i verticali, escalation a umano per
studio_medico_dentista. Il blocco vive nel testo BASE del prompt: la logica
A/B (PROMPT_VARIANTS) resta in coda, invariata.
"""

from src.agents.prompts import costruisci_blocco_lingue, costruisci_system_prompt
from src.models.schemas import ProfiloAttivita


def _profilo(verticale=None, **overrides):
    return ProfiloAttivita(
        nome="Trattoria Da Mario",
        tipo_attivita="ristorante",
        tono="cordiale",
        orari="Lun-Ven 12-15",
        servizi_principali=["Cucina tipica"],
        note_speciali=["Allergie allo staff"],
        verticale=verticale,
        **overrides,
    )


class TestBloccoLingue:
    def test_default_solo_italiano_best_effort(self):
        blocco = costruisci_blocco_lingue()
        assert "Lingue supportate dall'attivita': it" in blocco
        assert "Lingua di default: it" in blocco
        assert "best effort" in blocco
        assert "richiede_umano=True" not in blocco

    def test_lingue_personalizzate(self):
        blocco = costruisci_blocco_lingue(["it", "de"], "de")
        assert "it, de" in blocco
        assert "Lingua di default: de" in blocco

    def test_lingua_default_none_normalizzata_a_it(self):
        blocco = costruisci_blocco_lingue(["it", "en"], None)
        assert "Lingua di default: it" in blocco
        assert "None" not in blocco

    def test_studio_medico_escalation(self):
        blocco = costruisci_blocco_lingue(["it", "en"], "it", "studio_medico_dentista")
        assert "richiede_umano=True" in blocco
        assert "best effort" not in blocco

    def test_altro_verticale_best_effort(self):
        blocco = costruisci_blocco_lingue(["it"], "it", "ristorante")
        assert "best effort" in blocco
        assert "richiede_umano=True" not in blocco

    def test_verticale_none_best_effort(self):
        blocco = costruisci_blocco_lingue(["it"], "it", None)
        assert "best effort" in blocco
        assert "richiede_umano=True" not in blocco


class TestPromptResponder:
    def test_blocco_lingue_presente_nel_prompt(self):
        prompt = costruisci_system_prompt(_profilo())
        assert "LINGUE:" in prompt
        assert "best effort" in prompt
        assert "REGOLE DI ESCALATION" in prompt

    def test_verticale_senza_escalation_linguistica(self):
        prompt = costruisci_system_prompt(_profilo())
        assert "richiede_umano=True" not in prompt.split("LINGUE:")[1].split("\n\n")[0]

    def test_studio_medico_escalation_linguistica(self):
        prompt = costruisci_system_prompt(
            _profilo(verticale="studio_medico_dentista")
        )
        blocco = prompt.split("LINGUE:")[1]
        assert "richiede_umano=True" in blocco
        assert "best effort" not in blocco

    def test_lingue_custom_nel_prompt(self):
        prompt = costruisci_system_prompt(
            _profilo(lingue_supportate=["it", "en", "de"], lingua_default="de")
        )
        assert "it, en, de" in prompt
        assert "Lingua di default: de" in prompt

    def test_ab_variante_in_coda_al_blocco_lingue(self):
        base = costruisci_system_prompt(_profilo())
        concise = costruisci_system_prompt(_profilo(), variante="concise")
        assert len(concise) > len(base)
        assert "LINGUE:" in concise
        assert "conciso" in concise.lower() or "breve" in concise.lower()
        # il blocco lingue resta nel testo base, la variante lo segue
        assert concise.index("LINGUE:") < concise.lower().index("conciso")

    def test_control_prompt_invariato(self):
        assert costruisci_system_prompt(_profilo()) == costruisci_system_prompt(
            _profilo(), variante="control"
        )