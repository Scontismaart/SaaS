# Guardrails e qualità risposta (task 12)

Il pacchetto `src/core/guardrails/` contiene i controlli che stanno attorno
al responder, dal messaggio in ingresso alla risposta inviata al cliente.

```
messaggio cliente
  │
  ├─ opt-out / richiesta operatore / reminder prenotazioni   (pre-esistenti)
  ├─ feedback 👍/👎 emoji-only  ──────────────► message_feedback (no LLM)
  ├─ classificatore di intent (euristica → LLM economico se incerto)
  ├─ cache FAQ semantica (intent=faq, pgvector) ─► risposta in cache (no LLM)
  ├─ retrieval RAG (stesso embedding della cache)
  ├─ responder (routing cheap/premium anche in base all'intent)
  └─ VALIDATORE post-LLM
       ├─ trim: lunghezza > limite, markdown non renderizzabile
       └─ block: prezzi non presenti nel contesto RAG/profilo,
                  frasi di rinuncia, risposta vuota
             └─► fallback "ti metto in contatto con lo staff" + escalation HITL
```

## Componenti

### 1. Validatore post-LLM (`validator.py`)
Deterministico (regex/soglie), zero chiamate LLM, applicato sia al flusso
WhatsApp/Instagram reale sia alla preview del wizard onboarding.

- **Grounding prezzi**: ogni importo in euro presente nella risposta deve
  comparire nei chunk RAG o nel profilo dell'attività. Importo non
  verificabile ⇒ `block`: testo sostituito dal fallback staff,
  `richiede_umano=True` ⇒ escalation HITL esistente + email al titolare +
  usage event `guardrail_block` (con motivo e violazioni).
- **Trim**: risposta oltre `GUARDRAIL_MAX_REPLY_CHARS` (default 800)
  accorciata a confine di frase; marker markdown rimossi.

### 2. Classificatore di intent (`intent_classifier.py`)
Gira prima del responder. Euristica keyword prima (gratuita); il modello
economico (`OPENROUTER_MODEL_INTENT`, default = `OPENROUTER_MODEL_CHEAP`)
viene chiamato solo se l'euristica è incerta, con timeout
`GUARDRAIL_INTENT_TIMEOUT` e fallback euristico su errore. Mai bloccante.

L'intent alimenta: il routing del modello (`faq`/`chitchat` → cheap,
`booking`/`complaint` → premium, `reason="intent_classified"`), il gating
della cache FAQ e i metadata degli usage events
(`ai_response.intent`, event `intent_classification` quando serve l'LLM).

### 3. Cache FAQ semantica (`faq_cache.py` + tabella `faq_cache`, migration 031)
Le domande FAQ ripetute vengono servite senza passare dal responder
(usage event `cache_hit` = risparmio token). Matching semantico con lo
stesso embedding MiniLM del RAG (il processor ne calcola uno solo per
messaggio): soglia `GUARDRAIL_CACHE_THRESHOLD` (distanza cosine, default
0.08), TTL `GUARDRAIL_CACHE_TTL_HOURS` (default 72), interruttore
`GUARDRAIL_CACHE_ENABLED`. Vengono cachate SOLO risposte effettivamente
inviate con guardrail ok, senza escalation né prenotazione. Ogni upload
o eliminazione documento in `/api/documenti/*` invalida l'intera cache
dell'org (i prezzi potrebbero essere cambiati).

### 4. A/B test dei prompt (`src/agents/prompts.py`)
`PROMPT_VARIANTS` definisce le varianti (`control` = comportamento attuale,
`concise` = risposte più brevi); `GUARDRAIL_AB_VARIANTS` attiva quelle del
test. Assegnazione deterministica per tenant (`sha256(org_id)`): lo stesso
locale vede sempre lo stesso stile. La variante finisce nei metadata
dell'usage event `ai_response` e nella `faq_cache`.

### 5. Feedback 👍/👎 (`feedback.py` + tabella `message_feedback`, migration 031)
- **Cliente**: un messaggio che contiene solo un pollice (👍/👎 con skin
  tones) viene registrato come feedback sull'ultima risposta AI della
  conversazione; il messaggio non genera risposta.
- **Staff**: pulsanti 👍/👎 sulle bolle AI nel thread dell'inbox →
  `POST /api/inbox/messages/{id}/feedback` (JWT richiesto: API key di
  servizio riceve 403; cross-tenant 404; messaggi inbound 422).
  Idempotente per operatore (ri-votare aggiorna il giudizio).

Il log `message_feedback` joinato con `prompt_variant` e `intent` negli
`usage_events` è la base per misurare quale variante/prompt rende meglio.

## Bug latente corretto contestualmente
`messages.handling_type` ora viene valorizzato dal codice su ogni path
(`ai_handled`, `escalated`, `automation`, `opt_out`, `suspended`,
`feedback` per gli inbound; `ai_handled`/`human` per gli outbound).
Prima restava NULL e il trigger `event_log` calcolava sempre
`gestito_da_ai = false`.

## Configurazione (.env.example)
Vedi il blocco "Guardrails (task 12)" in `.env.example`:
`OPENROUTER_MODEL_INTENT`, `GUARDRAIL_INTENT_LLM_ENABLED`,
`GUARDRAIL_INTENT_TIMEOUT`, `GUARDRAIL_MAX_REPLY_CHARS`,
`GUARDRAIL_CACHE_ENABLED`, `GUARDRAIL_CACHE_THRESHOLD`,
`GUARDRAIL_CACHE_TTL_HOURS`, `GUARDRAIL_AB_VARIANTS`.

## Limiti noti / non in scope
- Le *reaction* WhatsApp/Instagram (evento webhook dedicato) non sono
  gestite: il feedback cliente arriva solo come messaggio emoji-only.
- Il validatore non copre il path recensioni (`crew_runner_review.py`).
- Aggregati/dashboard dei feedback: i dati ci sono, la vista arriva con
  la task 17 (analytics).
