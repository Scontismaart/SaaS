# LLM Token/Cost Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completare l'invariante 8 (AGENTS.md): ogni risposta AI registra il modello EFFETTIVO (dopo fallback), i token prompt/completion reali, la latenza e una stima di costo — invece dell'unico "quantity=1" col modello pianificato di oggi.

**Architecture:** `crew_runner.genera_risposta[_async]` accetta un paramentro opzionale `usage_sink: dict | None`. A kickoff riuscito riempie il sink con `model_effettivo`, `prompt_tokens`/`completion_tokens`/`total_tokens` (da `crew.usage_metrics` di CrewAI 1.15.4, con getattr difensivo), `latenza_ms` e `fallback_usato`. Il chiamante (inbound_processor, simulatore) mette il sink nel metadata dell'usage event già esistente — nessuna modifica allo schema DB. Nuova funzione pura `stima_costo_eur(model, prompt_tokens, completion_tokens)` in `llm_routing.py`: mappa prezzi indicativi per 1M token per i modelli noti, `None` se sconosciuto. Il metadata dell'intent classifier guadagna il campo `model`.

**Tech Stack:** CrewAI `usage_metrics` (prompt_tokens/completion_tokens), pytest con fake crew (monkeypatch di `crea_crew` nel namespace di crew_runner).

**Spec:** Audit 2026-09-01 — gap RAG/tracking #3 (nessuna attribuzione token/costo, modello pianificato loggato invece dell'effettivo) e #4 (intent LLM senza modello nel metadata). Scelta: stima di costo approssimativa lato applicazione (i provider non ritornano costi); `None` quando il prezzo non è noto è preferibile a un numero inventato.

## Global Constraints

- Firma pubblica `genera_rispora_async(...) -> RispostaOutput` invariata: `usage_sink` è opzionale a coda, nessun chiamante esistente si rompe.
- Nessuna modifica schema DB: i token/viaggiano nel metadata JSONB di `usage_events`.
- Fail-soft: qualunque problema nel leggere `usage_metrics` non deve mai rompere la generazione risposta.
- Le stime di costo sono dichiarate tali (chiave `stima_costo_eur`).

---

### Task 1: `stima_costo_eur` in `llm_routing.py`

**Files:**
- Modify: `src/core/llm_routing.py`
- Test: `tests/core/test_stima_costo.py` (nuovo)

**Interfaces:**
- Produces: `stima_costo_eur(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> float | None` — costo indicativo in EUR, None se prezzi sconosciuti o token None.

- [ ] **Step 1: Test che fallisce** — `tests/core/test_stima_costo.py`:

```python
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
```

- [ ] **Step 2: Run** `python -m pytest tests/core/test_stima_costo.py -v` → FAIL ImportError.

- [ ] **Step 3: Implementazione** in `llm_routing.py`:

```python
# Prezzi INDICATIVI per 1M token (prompt, completion) in EUR, per la stima
# di costo dell'invariante 8. Non sono fatture: sono stime lato app.
_TOKEN_PRICES_EUR_PER_1M: dict[str, tuple[float, float]] = {
    "mistral-small": (0.2, 0.6),
    "mistral-medium": (2.7, 8.1),
    "gpt-oss-120b": (0.1, 0.5),
    "gpt-4o-mini": (0.15, 0.6),
}


def stima_costo_eur(model, prompt_tokens, completion_tokens):
    """Stima indicativa di costo EUR per una chiamata, None se il modello
    non e' in tabella o i token mancano."""
    if prompt_tokens is None or completion_tokens is None:
        return None
    nome = (model or "").split("/")[-1].strip().lower()
    prezzi = _TOKEN_PRICES_EUR_PER_1M.get(nome)
    if not prezzi:
        return None
    p, c = prezzi
    return round(prompt_tokens / 1e6 * p + completion_tokens / 1e6 * c, 6)
```

- [ ] **Step 4: Run** → 4 PASS.

---

### Task 2: `usage_sink` in `crew_runner` + integrazione chiamanti

**Files:**
- Modify: `src/core/crew_runner.py`, `src/whatsapp/inbound_processor.py` (~riga 422-465), `src/api/main.py` (simulatore), `src/core/guardrails/intent_classifier.py` non serve (il modello si aggiunge dal chiamante)
- Test: `tests/core/test_crew_usage.py` (nuovo)

**Interfaces:**
- Produces: param `usage_sink: dict | None = None` su `genera_rispora`/`genera_rispora_async`; chiavi riempite: `model_effettivo: str`, `fallback_usato: bool`, `latenza_ms: int`, `prompt_tokens/completion_tokens/total_tokens: int | None`. Consumate da inbound_processor (metadata "ai_response") e main.py (metadata "simulatore").

- [ ] **Step 1: Test che fallisce** — `tests/core/test_crew_usage.py`:

```python
import asyncio
from types import SimpleNamespace

import pytest

import src.core.crew_runner as crew_runner
from src.models.schemas import MessaggioInput, ProfiloAttivita, RispostaOutput


class FakeCrew:
    def __init__(self):
        self.usage_metrics = SimpleNamespace(
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            cached_prompt_tokens=0, success_rate=1.0,
        )

    async def kickoff_async(self):
        return RispostaOutput(risposta="ciao", richiede_umano=False, motivo="ok")


def _profilo():
    return ProfiloAttivita(nome="Test", tipo_attivita="ristorante", tono="cordiale", orari="9-18")


@pytest.mark.asyncio
async def test_sink_riempito_con_metriche_reali(monkeypatch):
    creati = []
    def fake_crea_crew(*args, **kwargs):
        crew = FakeCrew()
        creati.append((kwargs.get("model"), crew))
        return crew
    monkeypatch.setattr(crew_runner, "crea_crew", fake_crea_crew)

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
        crew = object.__new__(FakeCrew)  # senza usage_metrics
        return crew
    def fake_crea_crew_rotto_primo_modello(*args, **kwargs):
        if kwargs.get("model") == "modello-test":
            raise RuntimeError("down")
        crew = object.__new__(FakeCrew)
        return crew
    monkeypatch.setattr(crew_runner, "crea_crew", fake_crea_crew_rotto_primo_modello)
    monkeypatch.setattr(
        crew_runner, "route_llm",
        lambda req: SimpleNamespace(model="modello-test", fallback_models=["modello-fallback"],
                                    tier="premium", reason="test"),
    )
    monkeypatch.setattr(crew_runner, "_route_request_for_message", lambda *a, **k: None)

    sink = {}
    await crew_runner.genera_risposta_async(MessaggioInput(testo="ciao"), _profilo(), usage_sink=sink)
    assert sink["model_effettivo"] == "modello-fallback"
    assert sink["fallback_usato"] is True
    assert sink["prompt_tokens"] is None
```

(Nota: monkeypatchare anche `route_llm` nel namespace di crew_runner per non dipendere dall'env.)

- [ ] **Step 2: Run** → FAIL TypeError (param usage_sink inesistente).

- [ ] **Step 3: Implementazione in `crew_runner.py`** (entrambe le funzioni):

```python
import time


def _riempi_sink(sink, model, fallback_usato, inizio, crew):
    """Invariante 8: metriche reali della chiamata (fail-soft)."""
    if sink is None:
        return
    sink["model_effettivo"] = model
    sink["fallback_usato"] = fallback_usato
    sink["latenza_ms"] = int((time.monotonic() - inizio) * 1000)
    metrics = getattr(crew, "usage_metrics", None)
    sink["prompt_tokens"] = getattr(metrics, "prompt_tokens", None)
    sink["completion_tokens"] = getattr(metrics, "completion_tokens", None)
    sink["total_tokens"] = getattr(metrics, "total_tokens", None)
```

In `genera_rispora_async`, aggiungere il param e nel loop:

```python
async def genera_risposta_async(..., usage_sink: dict | None = None) -> RispostaOutput:
    ...
    inizio = time.monotonic()
    async with LLM_CONCURRENCY_SEM:
        for idx, model in enumerate([route.model, *route.fallback_models]):
            try:
                crew = crea_crew(...)
                out = _validate_output(await crew.kickoff_async())
                _riempi_sink(usage_sink, model, idx > 0, inizio, crew)
                return out
            except Exception as exc:
                errors.append(f"{model}: {exc}")
```

Stessa cosa in `genera_rispora` (sync, `time.monotonic()`).

- [ ] **Step 4: Integrazione chiamanti**

`inbound_processor.py` (~422): prima della chiamata:

```python
                    usage = {}
                    risposta = await genera_risposta_async(
                        messaggio, profilo,
                        cronologia=cronologia,
                        billing=state,
                        contesto_documenti=contesto.testo,
                        intent=intent_result.intent,
                        variante=variante_prompt,
                        contesto_disponibilita=contesto_disp,
                        usage_sink=usage,
                    )
```

Nel metadata dell'usage event "ai_response" (~457) aggiungere:

```python
                            **{
                                k: usage[k] for k in
                                ("model_effettivo", "fallback_usato", "latenza_ms",
                                 "prompt_tokens", "completion_tokens", "total_tokens")
                                if k in usage
                            },
                            "stima_costo_eur": stima_costo_eur(
                                usage.get("model_effettivo") or route.model,
                                usage.get("prompt_tokens"), usage.get("completion_tokens"),
                            ),
```

(importare `stima_costo_eur` da `src.core.llm_routing`). Nel metadata dell'event "intent_classification" (~296) aggiungere `"model": _modello_intent()` — importare `from src.core.guardrails.intent_classifier import classifica_intent, _modello_intent`? Meglio rendere pubblica: rinominare l'helper in `modello_intent()` mantenendo alias `_modello_intent` (il modulo lo usa internamente).

`main.py` simulatore: `usage = {}` passato come `usage_sink=usage` a genera_risposta_async; nel `_record_ai_usage` metadata aggiungere `"model_effettivo": usage.get("model_effettivo")`, token e stima (se presenti).

- [ ] **Step 5: Run tutti i test**

Run: `python -m pytest tests/core/test_crew_usage.py tests/core/test_stima_costo.py tests/whatsapp/test_inbound_processor.py tests/unit/guardrails -q`
Expected: PASS (test_inbound_processor mocka genera_risposta_async: verificare che i mock usino **kwargs o aggiungere usage_sink ai mock — se un mock ha firma rigida, aggiornarlo con `**kwargs`)

- [ ] **Step 6: py_compile dei file toccati** → OK.

---

## Esito (2026-09-01)

Task 1-2 eseguiti inline. `_modello_intent` esposta come alias pubblico `modello_intent` (usato nel metadata dell'usage event intent_classification). Sink integrato in inbound_processor ("ai_response": model_effettivo, fallback_usato, latenza_ms, token, stima_costo_eur) e nel simulatore (/api/messaggio). I mock AsyncMock dei test esistenti accettano il nuovo kwarg senza modifiche.

Test: test_crew_usage 2 passed, test_stima_costo 4 passed, guardrails+dashboard+billing 65 passed totali. Test pg_pool: errore ambiente preesistente.

### Review cumulativa finale

Risolti: alias prezzi per i modelli default di routing (mistral-small-latest, mistral-medium-2508) con test dedicato che copre i default; fallback webhook trial derivato dal DB (vedi piano plan-enforcement-trial). Follow-up registrato: RAG su canale WhatsApp non verifica has_rag (decisione di prodotto: behandamento KB pre-esistente su piani inferiori).
