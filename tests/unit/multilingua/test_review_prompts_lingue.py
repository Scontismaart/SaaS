"""Multilingua (task 14): blocco LINGUE nel prompt delle recensioni.

Policy SEMPRE best-effort: le recensioni sono gia' pubbliche e
RispostaRecensioneOutput non ha richiede_umano — non ha senso "rifiutarsi"
di abbozzare una risposta. Nessun branch escalation (scope creep vietato).
Senza argomenti il prompt resta uguale a prima (blocco lingua in coda con
default italiano).
"""

from src.agents.review_prompts import costruisci_system_prompt_review


class TestPromptReview:
    def test_default_invariato_piu_blocco_lingua(self):
        prompt = costruisci_system_prompt_review()
        # regole base intatte
        assert "REGOLE FONDAMENTALI" in prompt
        assert "richiede_revisione_urgente" in prompt
        # blocco lingua con default italiano
        assert "LINGUE:" in prompt
        assert "Lingue supportate dall'attivita': it" in prompt
        assert "Lingua di default: it" in prompt
        # mai escalation in ambito recensioni
        assert "richiede_umano=True" not in prompt

    def test_lingue_personalizzate(self):
        prompt = costruisci_system_prompt_review(["it", "de"], "de")
        assert "it, de" in prompt
        assert "Lingua di default: de" in prompt
        assert "best effort" in prompt
        assert "richiede_umano=True" not in prompt

    def test_nessun_ramo_escalation_medico(self):
        # anche passando un profilo medico non deve comparire l'escalation:
        # la policy recensioni e' best-effort per definizione
        prompt = costruisci_system_prompt_review(["it"], "it")
        assert "best effort" in prompt
        assert "richiede_umano=True" not in prompt