"""Guardrail post-LLM (task 12): le risposte che violano le regole vengono
corrette (trim) o bloccate (block -> fallback staff + escalation)."""

from src.core.guardrails.validator import (
    FALLBACK_STAFF_TEXT,
    applica_guardrail,
    valida_risposta,
)
from src.models.schemas import ProfiloAttivita, RispostaOutput


def _profilo(**over):
    base = {
        "nome": "Trattoria Da Mario",
        "tipo_attivita": "ristorante",
        "tono": "cordiale",
        "orari": "Lun-Ven 12-15, 19-23",
        "servizi_principali": ["Cucina tipica"],
        "note_speciali": ["Allergie sempre allo staff"],
    }
    base.update(over)
    return ProfiloAttivita(**base)


def _risposta(testo, **over):
    base = {
        "risposta": testo,
        "richiede_umano": False,
        "motivo": "info",
        "categoria": "info",
    }
    base.update(over)
    return RispostaOutput(**base)


class TestRisposteValide:
    def test_risposta_corta_senza_prezzi_passa_invariata(self):
        r = _risposta("Siamo aperti dalle 12 alle 15, ti aspettiamo!")
        esito = valida_risposta(r, [], _profilo())
        assert esito.azione == "none"
        assert esito.testo == r.risposta

    def test_prezzo_presente_nei_chunk_rag_passa(self):
        chunks = [{"content": "Il menu' del giorno costa 15 euro, bevande escluse."}]
        r = _risposta("Il menu' del giorno costa 15 euro!")
        esito = valida_risposta(r, chunks, _profilo())
        assert esito.azione == "none"

    def test_prezzo_presente_nel_profilo_passa(self):
        profilo = _profilo(note_speciali=["Menu' bambini 10 euro"])
        r = _risposta("Il menu' bambini costa 10 euro.")
        esito = valida_risposta(r, [], profilo)
        assert esito.azione == "none"

    def test_formati_prezzo_equivalenti_passano(self):
        """'15,50 €' nel RAG autorizza '€15.50' nella risposta: la virgola
        italiana e il punto vanno normalizzati prima del confronto."""
        chunks = [{"content": "Il calice costa 15,50 €"}]
        r = _risposta("Il calice costa €15.50, ottimo con il pesce.")
        esito = valida_risposta(r, chunks, _profilo())
        assert esito.azione == "none"


class TestPrezziNonVerificati:
    def test_prezzo_assente_dal_rag_viene_bloccato(self):
        chunks = [{"content": "Il menu' del giorno costa 15 euro."}]
        r = _risposta("Il menu' del giorno costa 25 euro!")
        esito = valida_risposta(r, chunks, _profilo())
        assert esito.azione == "block"
        assert esito.motivo == "prezzo_non_verificato"
        assert esito.testo == FALLBACK_STAFF_TEXT

    def test_prezzo_con_contesto_vuoto_viene_bloccato(self):
        """Senza chunk RAG non c'e' grounding: qualsiasi prezzo in risposta
        e' potenzialmente allucinato."""
        r = _risposta("La pizza margherita costa 8 euro.")
        esito = valida_risposta(r, [], _profilo())
        assert esito.azione == "block"
        assert esito.motivo == "prezzo_non_verificato"

    def test_orari_non_vengono_scambiati_per_prezzi(self):
        """'dalle 12 alle 15' non contiene simboli monetari: non deve
        triggerare il guardrail sui prezzi."""
        r = _risposta("Siamo aperti dalle 12 alle 15 e dalle 19 alle 23.")
        esito = valida_risposta(r, [], _profilo())
        assert esito.azione == "none"


class TestFrasiVietateEVuote:
    def test_frasi_di_rinuncia_vengono_bloccate(self):
        r = _risposta("Mi dispiace, non posso aiutarti con questa richiesta.")
        esito = valida_risposta(r, [], _profilo())
        assert esito.azione == "block"
        assert esito.motivo == "frase_vietata"

    def test_risposta_vuota_viene_bloccata(self):
        r = _risposta("   ", richiede_umano=False)
        esito = valida_risposta(r, [], _profilo())
        assert esito.azione == "block"
        assert esito.motivo == "risposta_vuota"


class TestCorrezioni:
    def test_markdown_viene_rimosso(self):
        r = _risposta("Ecco il **menu del giorno**:\n- Pasta 12 euro\n- Pesce")
        chunks = [{"content": "Pasta 12 euro nel menu"}]
        esito = valida_risposta(r, chunks, _profilo())
        assert esito.azione == "trim"
        assert "**" not in esito.testo
        assert "menu del giorno" in esito.testo

    def test_lunghezza_eccessiva_tagliata_a_confine_frase(self):
        testo = (
            "Gentile cliente, la ringraziamo per il messaggio. "
            "Siamo aperti dal lunedi' al sabato. La cucina apre alle 12. "
            "Il parcheggio e' gratuito davanti al locale. "
            "Per gruppi numerosi consigliamo la prenotazione. "
            "Attenderemo con piacere la sua visita nei prossimi giorni."
        )
        r = _risposta(testo)
        esito = valida_risposta(r, [], _profilo(), max_chars=100)
        assert esito.azione == "trim"
        assert len(esito.testo) <= 101  # il confine di frase non supera di molto il limite
        assert esito.testo.endswith(".")

    def test_lunghezza_senza_punteggiatura_taglio_duro(self):
        r = _risposta("parola " * 60)
        esito = valida_risposta(r, [], _profilo(), max_chars=50)
        assert esito.azione == "trim"
        assert len(esito.testo) <= 51
        assert esito.testo.endswith("…")

    def test_limite_da_env(self, monkeypatch):
        monkeypatch.setenv("GUARDRAIL_MAX_REPLY_CHARS", "40")
        r = _risposta("Frase piu' lunga del limite configurato via environment variabile.")
        esito = valida_risposta(r, [], _profilo())
        assert esito.azione == "trim"
        assert len(esito.testo) <= 41


class TestApplicaGuardrail:
    def test_none_lascia_la_risposta_invariata(self):
        r = _risposta("Tutto ok!")
        esito = valida_risposta(r, [], _profilo())
        assert applica_guardrail(r, esito) is r

    def test_trim_sostituisce_solo_il_testo(self):
        r = _risposta("   ".join(["testo"] * 300))
        esito = valida_risposta(r, [], _profilo(), max_chars=30)
        out = applica_guardrail(r, esito)
        assert out.risposta == esito.testo
        assert out.richiede_umano is False
        assert out.motivo == r.motivo

    def test_block_imposta_fallback_e_umano(self):
        r = _risposta("Costa 99 euro!", motivo="info")
        esito = valida_risposta(r, [], _profilo())
        out = applica_guardrail(r, esito)
        assert out.risposta == FALLBACK_STAFF_TEXT
        assert out.richiede_umano is True
        assert out.motivo == "guardrail_prezzo_non_verificato"
