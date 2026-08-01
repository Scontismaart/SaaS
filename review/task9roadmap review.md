# Task 9 — Google Reviews: Cambiamenti apportati

## File nuovi

### `src/core/db/migrations/022_reviews_ext.sql`
Migration SQL che estende la tabella `reviews`:

| Colonna | Tipo | Default | Note |
|---------|------|---------|------|
| `bozza_risposta` | TEXT | `''` | Bozza generata dal crew AI |
| `sentiment` | TEXT | `''` | Sentiment estratto dall'AI |
| `categoria` | TEXT | `''` | Categoria recensione |
| `richiede_revisione_urgente` | BOOLEAN | `FALSE` | Flag urgenza |
| `stato` | TEXT | `'nuova'` | Valori validi: `nuova`, `bozza_generata`, `approvata`, `pubblicata`, `errore`, `conflitto` (validato a livello applicativo, **non** enum PG) |
| `external_id` | TEXT | — | ID esterno (Google review ID, nullable) |
| `published_at` | TIMESTAMPTZ | — | Data pubblicazione risposta |
| `is_anonymized` | BOOLEAN | `FALSE` | Flag GDPR per soft-delete |

Vincoli:
- `UNIQUE(organization_id, external_id)` — dedup multi-tenant (solo righe con `external_id` valorizzato)
- RLS abilitata con policy `reviews_org_member` (stesso pattern di `019_google_calendar_credentials.sql`)

---

## File modificati

### `src/models/schemas.py`

**`RecensioneInput`** — aggiunto campo:
```python
external_id: str | None = Field(default=None)
```
(Nessun campo `organization_id` — deriva solo dal token JWT autenticato, mai dal body)

**`RispostaRecensioneOutput`** — aggiunto campi:
```python
id: str
stato: str
```

**Nuovo**: `VALID_STATI_RECENSIONE` frozenset per validazione applicativa degli stati:
```python
VALID_STATI_RECENSIONE = frozenset({
    "nuova", "bozza_generata", "approvata", "pubblicata", "errore", "conflitto",
})
```

### `src/core/db/repository.py`

Metodi esistenti modificati:

| Metodo | Modifica |
|--------|----------|
| `create_review()` | Parametri estesi con `external_id`, `bozza_risposta`, `sentiment`, `categoria`, `richiede_revisione_urgente`, `stato` — INSERT corrispondente nella tabella |

Nuovi metodi:

| Metodo | Firma | Descrizione |
|--------|-------|-------------|
| `get_review(org_id, review_id)` | async | SELECT scoped per org |
| `get_review_by_external_id(org_id, external_id)` | async | Dedup — cerca per external_id |
| `list_reviews(org_id, stato, fonte, page, limit)` | async | Lista con filtri + paginazione |
| `update_review(org_id, review_id, **kwargs)` | async | UPDATE dinamico per stato/bozza |
| `approve_review(org_id, review_id)` | async | `SELECT FOR UPDATE` + atomic update a `approvata` — idempotente su doppio click |
| `get_review_analytics(org_id, giorni)` | async | Sentiment trend, distribuzione stelle/categorie/fonti — esclude `is_anonymized = TRUE` dal dettaglio ma include nei totali aggregati |

### `src/api/main.py`

**`POST /api/recensione`** — endpoint riscritto:

Prima:
```python
@app.post("/api/recensione", response_model=RispostaRecensioneOutput)
def ricevi_recensione(recensione: RecensioneInput, user: dict = Depends(...)):
    output = genera_risposta_recensione(...)   # sync
    _storico_eventi.append(...)                # solo in-memory
    return output                              # senza id/stato
```

Dopo:
```python
@app.post("/api/recensione", response_model=RispostaRecensioneOutput)
async def ricevi_recensione(recensione: RecensioneInput, request: Request, user: dict = Depends(...)):
    output = await asyncio.to_thread(lambda: genera_risposta_recensione(...))  # offload a thread
    org_id = user["organization_id"]   # dal token JWT, mai dal body
    if org_id:
        review = await repo.create_review(...)   # persistenza DB
        review_id = str(review["id"])
    _storico_eventi.append(...)                  # ancora per backward compat dashboard
    return RispostaRecensioneOutput(id=review_id, stato="bozza_generata", ...)
```

Dettagli:
- `organization_id` estratto dal token JWT autenticato (via `require_ruolo` → `get_organization_context`)
- Generazione bozza AI offloadata a thread pool (`asyncio.to_thread`) per non bloccare event loop
- Persistenza DB fallisce silenziosamente in demo mode (repo=None)
- `_storico_eventi` mantenuto per backward compat — refactor futuro separato (task non in questa PR)
- Response ora include `id` e `stato`

Import aggiunto:
```python
from src.core.auth.dependencies import get_repo, require_ruolo, close_http_client
```

---

## Spike eseguiti

### Google Reply API (updateReply)
- **Endpoint**: `PUT https://mybusiness.googleapis.com/v4/{name=accounts/*/locations/*/reviews/*}/reply`
- **Comportamento**: **upsert** — crea risposta se non esiste, **sovrascrive** se esiste già
- **Nessun errore** `ALREADY_EXISTS` o `CONFLICT` — la sovrascrittura è silenziosa
- **Implicazione**: serve fetch preventivo (`reviews.get`) per rilevare risposta già esistente prima di chiamare `updateReply`. Non possiamo affidarci a errori API.

### Email service exception handling
- `email_service.py` ha già gestione eccezioni robusta: `_send_with_retry` con tenacity (3 tentativi, backoff esponenziale) + `_worker` con try/except + `RetryError` catch + logging critico + `task_done()` in finally
- Pattern replicabile per task queue in Fase 5

---

## Piani futuri (non implementati in questa task)

| Fase | Cosa | Dipende da |
|------|------|------------|
| 3 | OAuth Business Profile (tabella separata `google_business_credentials`, router `/api/reviews/google/{auth,callback,status,disconnect}`) | Approvazione Google Business Profile API (weeks, esterna) |
| 4 | GoogleReviewSource reale: fetch `accounts.locations.reviews.list` + per-org backoff + gestione token scaduto | Fase 3 |
| 5 | Scheduler con lock distribuito (`pg_try_advisory_lock(int, int)` con `hashtextextended()` per collision-free 64-bit) + task queue asincrona con exception handling | Fase 4 |
| 6 | Pubblica risposta: fetch preventivo `reviews.get` → `updateReply` — gestione conflitto se risposta già esistente | Fase 4 |
| 7 | TripAdvisor: mini-form UI (modale dashboard), solo incollazione manuale, nessun fetch | — |
| 8 | GDPR retention: agganciare `reviews` a job notturno con `is_anonymized = TRUE` | — |
| 9 | Analytics endpoint (`GET /api/recensioni/analytics`) | Metodo `get_review_analytics()` già implementato |
