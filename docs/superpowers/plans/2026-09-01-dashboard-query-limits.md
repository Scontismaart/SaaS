# Dashboard Query Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare il carico lineare sulla storia dell'organizzazione dalle viste Panoramica: la query che alimenta `/api/dashboard` e `/api/dashboard/prioritari` (ricalcolata dal client ogni 5 secondi) non ha né filtro temporale né LIMIT, e l'endpoint prioritari ri-esegue l'intera query filtrando poi in Python.

**Architecture:** La funzione condivisa `recupera_eventi_dashboard` (`src/api/main.py`) riceve due parametri SQL aggiuntivi: una finestra temporale di 30 giorni applicata ai rami `event_log`/`messages`/`reviews` del CTE, e un LIMIT 500 sul result set finale ordinato per timestamp. L'endpoint `/api/dashboard/prioritari` smette di riusare la funzione completa: una nuova funzione `recupera_eventi_prioritari` riusa lo stesso CTE (estratto in costante modulo) ma filtra `priorita <> 'bassa'` e ordina/limita direttamente in SQL.

**Tech Stack:** FastAPI, asyncpg, pytest con mock pool (i test esistenti in `tests/core/test_dashboard_persistence.py` non richiedono Postgres).

**Spec:** Audit dashboard 2026-09-01 — problema #1 (query senza LIMIT/filtro eseguita 2 volte ogni 5s) e relativo rimedio minimo; KPI UI usa finestra sparkline di 7 giorni (`web/app.js:3298-3336`), quindi una finestra server di 30 giorni non altera i KPI.

## Global Constraints

- Tenant isolation invariata: `$1` resta sempre `organization_id` in ogni query.
- Nessuna modifica al response model (`list[EventoDashboard]`) né al contratto API.
- La finestra server (30 giorni) deve restare strettamente superiore alla finestra UI (7 giorni) per non rompere trend/sparkline.
- Non usare `NOW()` lato client: la finestra è calcolata dal DB (`make_interval`).
- Fallback demo `_storico_eventi` resta invariato (scope del fix: performance, non semantica fallback).

---

### Task 1: Costanti modulo + finestra temporale e LIMIT in `recupera_eventi_dashboard`

**Files:**
- Modify: `src/api/main.py` (funzione `recupera_eventi_dashboard`, ~riga 1140-1269)
- Test: `tests/core/test_dashboard_persistence.py`

**Interfaces:**
- Consumes: firma esistente `recupera_eventi_dashboard(pool, org_id)` — invariata.
- Produces: costanti modulo `DASHBOARD_EVENTI_WINDOW_DAYS = 30` e `DASHBOARD_EVENTI_MAX = 500`; parametri SQL della query diventano `(org_uuid, DASHBOARD_EVENTI_WINDOW_DAYS, DASHBOARD_EVENTI_MAX)`.

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere in fondo a `tests/core/test_dashboard_persistence.py`:

```python
import src.api.main as api_main


@pytest.mark.asyncio
async def test_recupera_eventi_dashboard_applica_finestra_e_limit():
    """La query deve ricevere (org, finestra_giorni, limit) e applicare
    filtro temporale + LIMIT: senza, l'endpoint scarica l'intera storia
    dell'org a ogni poll di 5 secondi."""
    org_id = str(uuid.uuid4())
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    await recupera_eventi_dashboard(mock_pool, org_id)

    args = mock_conn.fetch.call_args.args
    assert args[1] == uuid.UUID(org_id)
    assert args[2] == api_main.DASHBOARD_EVENTI_WINDOW_DAYS
    assert args[2] > 7, "la finestra server deve coprire la sparkline UI (7 giorni)"
    assert args[3] == api_main.DASHBOARD_EVENTI_MAX
    sql = args[0]
    assert "make_interval" in sql, "manca il filtro temporale"
    assert "LIMIT" in sql.upper(), "manca il LIMIT sul result set"
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run: `python -m pytest tests/core/test_dashboard_persistence.py::test_recupera_eventi_dashboard_applica_finestra_e_limit -v`
Expected: FAIL con `AttributeError: module 'src.api.main' has no attribute 'DASHBOARD_EVENTI_WINDOW_DAYS'`

- [ ] **Step 3: Implementare**

In `src/api/main.py`, sopra `recupera_eventi_dashboard` aggiungere:

```python
# Finestra e tetto del result set della Panoramica: senza, l'endpoint
# scaricherebbe l'intera storia dell'org a ogni poll di 5 secondi
# (client: web/app.js avviaPanoramicaPolling). La UI usa una sparkline
# di 7 giorni, quindi 30 giorni coprono con margine.
DASHBOARD_EVENTI_WINDOW_DAYS = 30
DASHBOARD_EVENTI_MAX = 500
```

Nel CTE `raw_events`, aggiungere a ciascuno dei tre rami la stessa condizione temporale:

```sql
-- ramo 1 (event_log), dopo "WHERE e.organization_id = $1":
                      AND e.created_at >= NOW() - make_interval(days => $2)
-- ramo 2 (messages), dopo "AND m.deleted_at IS NULL":
                      AND m.created_at >= NOW() - make_interval(days => $2)
-- ramo 3 (reviews), dopo "WHERE r.organization_id = $1":
                      AND r.created_at >= NOW() - make_interval(days => $2)
```

Sostituire la SELECT finale:

```sql
                SELECT * FROM (
                    SELECT DISTINCT ON (id) *
                    FROM raw_events
                    ORDER BY id, timestamp DESC
                ) dedup
                ORDER BY timestamp DESC
                LIMIT $3
```

E la chiamata a `conn.fetch` passa i nuovi parametri:

```python
            rows = await conn.fetch("""<query aggiornata>""",
                org_uuid, DASHBOARD_EVENTI_WINDOW_DAYS, DASHBOARD_EVENTI_MAX)
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `python -m pytest tests/core/test_dashboard_persistence.py -v`
Expected: 4 PASS (i 3 esistenti + il nuovo)

- [ ] **Step 5: Commit**

```bash
git add src/api/main.py tests/core/test_dashboard_persistence.py
git commit -m "perf(dashboard): finestra 30 giorni e LIMIT 500 sulla query Panoramica"
```

---

### Task 2: `/api/dashboard/prioritari` filtra e limita in SQL

**Files:**
- Modify: `src/api/main.py` (CTE estratto in costante `_DASHBOARD_EVENTI_CTE`; nuova funzione `recupera_eventi_prioritari`; endpoint `ottieni_eventi_prioritari` ~riga 1282-1296)
- Test: `tests/core/test_dashboard_persistence.py`

**Interfaces:**
- Consumes: costanti `DASHBOARD_EVENTI_WINDOW_DAYS`, `DASHBOARD_EVENTI_MAX` (Task 1); CTE condiviso `_DASHBOARD_EVENTI_CTE` (stringa SQL del ramo UNION, parametri `$1` org, `$2` giorni).
- Produces: `async def recupera_eventi_prioritari(pool, org_id, limite: int) -> list[EventoDashboard]` — filtra `priorita <> 'bassa'`, ordina `(alta prima, timestamp ASC)`, LIMIT `$3`, tutto in SQL.

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere in fondo a `tests/core/test_dashboard_persistence.py`:

```python
@pytest.mark.asyncio
async def test_recupera_eventi_prioritari_filtra_in_sql():
    """I prioritari devono essere filtrati/ordinati/limitati dal DB:
    l'endpoint non deve piu' rieseguire la query completa e filtrare in Python."""
    from src.api.main import recupera_eventi_prioritari

    org_id = str(uuid.uuid4())
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await recupera_eventi_prioritari(mock_pool, org_id, limite=5)

    assert result == []
    args = mock_conn.fetch.call_args.args
    assert args[1] == api_main.DASHBOARD_EVENTI_WINDOW_DAYS
    assert args[2] == 5
    sql = args[0]
    assert "priorita <> 'bassa'" in sql or "priorita != 'bassa'" in sql
    assert "CASE" in sql and "alta" in sql, "manca l'ordinamento alta-prima"
    assert "LIMIT $3" in sql
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run: `python -m pytest tests/core/test_dashboard_persistence.py::test_recupera_eventi_prioritari_filtra_in_sql -v`
Expected: FAIL con `ImportError: cannot import name 'recupera_eventi_prioritari'`

- [ ] **Step 3: Implementare**

Estrarre il corpo del CTE (i tre rami UNION) in una costante modulo con i parametri `$1` (org) e `$2` (giorni) già introdotti nel Task 1, poi riscrivere le due funzioni per comporla:

```python
_DASHBOARD_EVENTI_CTE = """
    WITH raw_events AS (
        -- 1. Eventi gia' registrati in event_log [... corpo dei tre rami UNION,
        --    identico a quello di recupera_eventi_dashboard, con i filtri
        --    make_interval(days => $2) introdotti nel Task 1 ...]
    )
"""


async def recupera_eventi_prioritari(pool, org_id, limite: int):
    """Eventi priorita' alta/media per la colonna Prioritari della
    Panoramica: filtro, ordinamento (alta prima, poi timestamp crescente)
    e LIMIT eseguiti dal database."""
    if not pool or not org_id:
        return []
    try:
        org_uuid = uuid.UUID(str(org_id))
    except (ValueError, TypeError):
        return []
    limite = max(1, min(int(limite or 5), 50))
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _DASHBOARD_EVENTI_CTE + """
                SELECT * FROM raw_events
                WHERE priorita <> 'bassa'
                ORDER BY CASE WHEN priorita = 'alta' THEN 0 ELSE 1 END,
                         timestamp ASC
                LIMIT $3
                """,
                org_uuid, DASHBOARD_EVENTI_WINDOW_DAYS, limite)
        return [
            EventoDashboard(
                id=str(r["id"]),
                tipo_evento=r["tipo_evento"] if r["tipo_evento"] in ("messaggio", "recensione") else "messaggio",
                timestamp=r["timestamp"],
                priorita=r["priorita"] if r["priorita"] in ("alta", "media", "bassa") else "media",
                testo_originale=r["testo_originale"] or "",
                risposta_ai=r["risposta_ai"] or "",
                gestito_da_ai=bool(r["gestito_da_ai"]),
                dettagli=json.loads(r["dettagli"]) if isinstance(r["dettagli"], str) else (r["dettagli"] or {}),
            )
            for r in rows
        ]
    except Exception as e:
        logger.error("Errore recupero prioritari per org %s: %s", org_id, e)
        return []
```

Riscrivere l'endpoint per delegare:

```python
@app.get("/api/dashboard/prioritari", response_model=list[EventoDashboard])
async def ottieni_eventi_prioritari(
    request: Request,
    limite: int = 5,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    pool = getattr(request.app.state, "pool", None)
    org_id = user.get("organization_id")
    return await recupera_eventi_prioritari(pool, org_id, limite)
```

In variazione rispetto alla precedente logica Python, il fallback `recupera_eventi_dashboard` non viene invocato: per org valida con DB irraggiungibile si ritorna lista vuota invece dei dati demo (coerente con la nuova funzione; il ramo `/api/dashboard` principale conserva il fallback esistente).

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `python -m pytest tests/core/test_dashboard_persistence.py -v`
Expected: 5 PASS

- [ ] **Step 5: Smoke di sintassi endpoint**

Run: `python -m py_compile src/api/main.py`
Expected: nessun output (OK)

- [ ] **Step 6: Commit**

```bash
git add src/api/main.py tests/core/test_dashboard_persistence.py
git commit -m "perf(dashboard): prioritari filtrati e limitati in SQL senza doppia query"
```

---

### Task 3: Verifica regressioni e chiusura

- [ ] **Step 1: Test completi del modulo dashboard**

Run: `python -m pytest tests/core/test_dashboard_persistence.py -v`
Expected: 5 PASS

- [ ] **Step 2: Compilazione di tutti i file toccati**

Run: `python -m py_compile src/api/main.py`
Expected: OK

- [ ] **Step 3: Code review**

Usare lo skill requesting-code-review: dispatch subagent reviewer sul diff della feature (BASE = commit che precede il Task 1, HEAD = commit del Task 2), DESCRIPTION = piano `docs/superpowers/plans/2026-09-01-dashboard-query-limits.md`.

---

## Esito (2026-09-01)

Task 1-3 eseguiti inline (commit rimandati: il working tree contiene modifiche preesistenti non committate negli stessi file, che non devono finire in commit etichettati come questi fix).

Code review (subagent reviewer): 1 Critical, 5 Important, 4 Minor. Tutti gli issue risolti o documentati:
- **Critical**: `repo.get_organization` non esisteva -> il simulatore usava sempre il profilo demo. Aggiunto `CoreRepository.get_organization` e log a `warning` sul fallback.
- **Important #2**: simulatore org ora passa il billing snapshot a `genera_risposta_async` e registra usage (`task_type="simulatore"`).
- **Important #3**: chiave conv_store namespaced per org (`"{org_id}:{id_conversazione}"`).
- **Important #4**: vincolo pool documentato nel docstring di `slot_lock` (refactor same-connection rimandato).
- **Important #5**: deviation /api/report documentata in commento all'endpoint.
- **Minor**: descrizione normalizzata (`re.sub(r"\s+", " ")`) contro prompt restructuring; test rinforzato (`count(make_interval) == 3`); `_storico_eventi` alimentato solo dal path demo anonimo; migration 044 da applicare manualmente in staging/prod prima del deploy.

Test: `tests/core/test_dashboard_persistence.py` 5 passed, guardrails 45 passed.
