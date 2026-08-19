# Piano: TASK-043 — Cutoff timezone-aware in `get_review_analytics` + test dedicati

- Complessità: M
- Approvato da: manager
- Data: 2026-08-19

> Nota: il task input non riportava un `task-id` esplicito; il manager assegna `TASK-043`.

## Contesto tecnico (verificato sul codice)

- `src/core/db/repository.py`, righe 274-319: `get_review_analytics(self, organization_id, giorni=90)`.
  - Riga 275: import locale `from datetime import datetime, timedelta`.
  - Riga 276: `cutoff = datetime.utcnow() - timedelta(days=giorni)` → finding ruff **DTZ003** (`datetime.utcnow()` deprecato in Python 3.12).
- La colonna `reviews.created_at` è `TIMESTAMPTZ DEFAULT NOW()` (schema.sql riga 61; estensione in `022_reviews_ext.sql` aggiunge `sentiment`, `categoria`, `is_anonymized`, ecc.).
- `create_review` (righe 171-190) NON accetta `created_at`: nei test serve una INSERT diretta via `repo.pool` (attributo pubblico di `CoreRepository`).
- `approve_review` (righe 253-272) NON va toccata: il doppio `async with` (acquire + transaction) è intenzionale per il lock transazionale.
- `tests/core/test_repository_reviews.py`: oggi 2 test, `pytestmark = pytest.mark.usefixtures("reset_db")`, fixture `repo` e `sample_org` dal conftest (PostgresContainer pgvector, Docker richiesto).
- `get_review_analytics` non espone un parametro `cutoff`: l'unica leva per "forzare" la finestra è il parametro `giorni`.

---

## Fase 1 — Analisi

**Input:** task TASK-043, `src/core/db/repository.py` (righe 171-319), `tests/core/test_repository_reviews.py`, `tests/core/conftest.py`, `src/core/db/schema.sql`, `src/core/db/migrations/022_reviews_ext.sql`.

**Azioni:**
1. Confermare che l'unico punto da modificare nel repository sia la riga 276 (cutoff) e l'import locale a riga 275.
2. Confermare che `repo.pool` sia accessibile dai test (sì: `CoreRepository.__init__` salva `self.pool`).
3. Confermare che le colonne necessarie per gli INSERT di test esistano: `testo`, `valutazione_stelle`, `fonte`, `autore`, `created_at`, `sentiment`, `categoria` (schema.sql + 022_reviews_ext.sql).
4. Verificare che `sentiment_trend` filtri `is_anonymized = FALSE` (default FALSE → le review inserite nei test rientrano).
5. Verificare che Docker sia attivo prima di eseguire i test (`docker info`).

**Criteri di uscita:** individuati con precisione i file/righe da toccare; nessun'altra modifica necessaria alla logica, alle query o al formato del risultato.

---

## Fase 2 — Progettazione

**Input:** esito Fase 1.

**Azioni:**
1. **Refactor minimo** in `src/core/db/repository.py`:
   - Riga 275: `from datetime import datetime, timedelta` → `from datetime import datetime, timedelta, timezone`.
   - Riga 276: `cutoff = datetime.utcnow() - timedelta(days=giorni)` → `cutoff = datetime.now(timezone.utc) - timedelta(days=giorni)`.
   - Nessun'altra modifica a query, logica o struttura del risultato.
2. **Test** in `tests/core/test_repository_reviews.py`:
   - Helper `_insert_review(...)` che esegue INSERT diretta con `created_at` esplicito via `repo.pool.acquire()`.
   - Test 1: review dentro la finestra incluse in `sentiment_trend` e `star_distribution`.
   - Test 2: review più vecchia del cutoff esclusa.
   - Test 3: cutoff timezone-aware — stesso istante espresso in due fusi diversi (UTC e UTC+2) deve essere trattato identicamente; review fuori finestra espressa in +2 deve restare esclusa. La finestra è "forzata" tramite `giorni`.
3. **TDD**: i test vengono scritti e fatti fallire PRIMA della modifica al repository (con `datetime.utcnow()` i test 1-2 passano già, quindi il test 3 è quello che discrimina il comportamento timezone-aware; in ogni caso l'ordine TDD resta: test → verifica fallimento/rosso → implementazione → verde).

**Criteri di uscita:** progetto approvato; nessuna modifica a `approve_review`; nessun refactoring estraneo.

---

## Fase 3 — Test (scrivere i test PRIMA del codice, TDD)

**Input:** `tests/core/test_repository_reviews.py` esistente, conftest con fixture `repo`, `sample_org`, `reset_db`.

**Azioni:**
1. Aggiungere gli import in testa al file:
   ```python
   import uuid
   from datetime import datetime, timedelta, timezone
   ```
2. Aggiungere l'helper (a livello modulo, dopo gli import):
   ```python
   async def _insert_review(repo, organization_id, *, created_at,
                            testo="Recensione test", valutazione_stelle=4,
                            fonte="google", autore="Test Autore",
                            sentiment="positivo", categoria="cibo"):
       """INSERT diretta con created_at esplicito (create_review non lo espone)."""
       async with repo.pool.acquire() as conn:
           row = await conn.fetchrow(
               """
               INSERT INTO reviews (id, organization_id, testo, valutazione_stelle,
                                    fonte, autore, created_at, sentiment, categoria)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING *
               """,
               uuid.uuid4(), organization_id, testo, valutazione_stelle,
               fonte, autore, created_at, sentiment, categoria,
           )
           return dict(row)
   ```
3. Aggiungere i tre test:
   ```python
   @pytest.mark.asyncio
   async def test_get_review_analytics_includes_reviews_in_window(repo, sample_org):
       now = datetime.now(timezone.utc)
       await _insert_review(
           repo, sample_org["id"], created_at=now - timedelta(days=1),
           testo="Ottimo", valutazione_stelle=5, sentiment="positivo",
       )
       await _insert_review(
           repo, sample_org["id"], created_at=now - timedelta(days=5),
           testo="Discreto", valutazione_stelle=3, sentiment="neutro",
       )

       analytics = await repo.get_review_analytics(sample_org["id"], giorni=30)

       trend = {r["sentiment"]: r["cnt"] for r in analytics["sentiment_trend"]}
       assert trend.get("positivo") == 1
       assert trend.get("neutro") == 1

       stars = {r["valutazione_stelle"]: r["cnt"] for r in analytics["star_distribution"]}
       assert stars.get(5) == 1
       assert stars.get(3) == 1


   @pytest.mark.asyncio
   async def test_get_review_analytics_excludes_reviews_older_than_cutoff(repo, sample_org):
       now = datetime.now(timezone.utc)
       await _insert_review(
           repo, sample_org["id"], created_at=now - timedelta(days=100),
           testo="Vecchia", valutazione_stelle=2, sentiment="negativo",
       )

       analytics = await repo.get_review_analytics(sample_org["id"], giorni=90)

       assert analytics["sentiment_trend"] == []
       assert analytics["star_distribution"] == []


   @pytest.mark.asyncio
   async def test_get_review_analytics_cutoff_is_timezone_aware(repo, sample_org):
       now = datetime.now(timezone.utc)
       tz_plus2 = timezone(timedelta(hours=2))
       # Stesso istante espresso in due fusi diversi: deve contare in entrambi i casi
       # (finestra forzata con giorni=2 -> cutoff = now - 2 giorni).
       await _insert_review(
           repo, sample_org["id"], created_at=now - timedelta(days=1),
           testo="Dentro UTC", valutazione_stelle=5, sentiment="positivo",
       )
       await _insert_review(
           repo, sample_org["id"],
           created_at=(now - timedelta(days=1)).astimezone(tz_plus2),
           testo="Dentro +2", valutazione_stelle=4, sentiment="positivo",
       )
       # Fuori finestra, espresso in +2: deve restare escluso.
       await _insert_review(
           repo, sample_org["id"],
           created_at=(now - timedelta(days=3)).astimezone(tz_plus2),
           testo="Fuori +2", valutazione_stelle=1, sentiment="negativo",
       )

       analytics = await repo.get_review_analytics(sample_org["id"], giorni=2)

       stars = {r["valutazione_stelle"]: r["cnt"] for r in analytics["star_distribution"]}
       assert stars.get(5) == 1
       assert stars.get(4) == 1
       assert 1 not in stars  # la review fuori finestra non deve comparire
   ```
4. Eseguire i test per verificare il rosso (prima della modifica al repository):
   ```bash
   $env:PYTHONUTF8="1"; python -m pytest tests/core/test_repository_reviews.py -v --tb=short
   ```
   Atteso: i 2 test esistenti passano; i 3 nuovi test falliscono (il test 3 deve fallire perché `datetime.utcnow()` produce un cutoff naive e il confronto con istanti aware non è corretto; i test 1-2 possono passare già — il rosso obbligatorio è il test 3).

**Criteri di uscita:** i 3 nuovi test sono presenti nel file; eseguiti e osservati fallire (almeno il test timezone-aware) prima di toccare il codice applicativo.

---

## Fase 4 — Implementazione

**Input:** esito Fase 3 (test rossi), `src/core/db/repository.py`.

**Azioni:**
1. Modificare la riga 275:
   ```python
   from datetime import datetime, timedelta, timezone
   ```
2. Modificare la riga 276:
   ```python
   cutoff = datetime.now(timezone.utc) - timedelta(days=giorni)
   ```
3. NON toccare `approve_review` (righe 253-272) né alcun'altra riga del file.
4. NON modificare query, logica di raggruppamento o formato del risultato di `get_review_analytics`.

**Criteri di uscita:** diff minimo: 2 righe modificate in `repository.py`; nessun altro file applicativo toccato.

---

## Fase 5 — Verifica (comandi reali da `.agent/constitution.md`)

**Input:** implementazione completata.

**Azioni:**
1. Test del file (Docker attivo):
   ```bash
   $env:PYTHONUTF8="1"; python -m pytest tests/core/test_repository_reviews.py -v --tb=short
   ```
   Atteso: tutti i test del file passano (2 esistenti + 3 nuovi).
2. Test completi del repo (Docker attivo):
   ```bash
   $env:PYTHONUTF8="1"; python -m pytest -v --tb=short
   ```
   Atteso: nessuna regressione.
3. Lint sui soli file del task (il repo ha ~628 errori preesistenti con ruff 0.16.1, NON sistemarli):
   ```bash
   python -m ruff check src/core/db/repository.py tests/core/test_repository_reviews.py
   ```
   Atteso: nessun errore sui file toccati (in particolare DTZ003 eliminato).
4. Format sui soli file del task:
   ```bash
   python -m ruff format src/core/db/repository.py tests/core/test_repository_reviews.py
   ```

**Criteri di uscita:** test verdi, lint pulito sui file toccati, nessuna regressione.

---

## Fase 6 — Riparazione (se i test falliscono, max 3 iterazioni)

**Input:** esito Fase 5 (eventuali fallimenti).

**Azioni:**
1. Iterazione 1: analizzare il fallimento (log pytest `--tb=short`), correggere, rieseguire i test del file.
2. Iterazione 2: se ancora rosso, ripetere analisi + correzione + riesecuzione.
3. Iterazione 3: ultimo tentativo; se ancora rosso, fermarsi e segnalare all'operatore (nessun commit).
4. Se il fallimento riguarda il setup Docker/container, verificare `docker info` e riprovare; non "sistemare" i test per farli passare a forza.

**Criteri di uscita:** test verdi entro 3 iterazioni, oppure stop con segnalazione all'operatore.

---

## Fase 7 — Rilascio (commit, branch `ai/<slug>`, PR)

**Input:** esito Fase 5/6 (verde).

**Azioni:**
1. Creare il branch:
   ```bash
   git checkout -b ai/tz-aware-review-analytics-cutoff
   ```
2. Verificare il diff e lo staging (solo i 2 file del task):
   ```bash
   git status
   git diff
   git add src/core/db/repository.py tests/core/test_repository_reviews.py
   ```
3. Commit convenzionali (in italiano):
   ```bash
   git commit -m "fix(reviews): rendi timezone-aware il cutoff di get_review_analytics"
   git commit -m "test(reviews): copertura analitiche con created_at esplicito e fusi diversi"
   ```
   (oppure un unico commit se preferito, sempre convenzionale).
4. PR tramite `gh` (se disponibile):
   ```bash
   gh pr create --title "fix(reviews): cutoff timezone-aware in get_review_analytics" --body "TASK-043: sostituisce datetime.utcnow() (DTZ003) con datetime.now(timezone.utc) e aggiunge test dedicati."
   ```
   Se `gh` non è disponibile, stampare il comando `gh pr create` da eseguire manualmente.
5. Aggiornare il grafo della conoscenza (regola AGENTS.md):
   ```bash
   graphify update .
   ```

**Criteri di uscita:** branch `ai/tz-aware-review-analytics-cutoff` creato, commit convenzionali, PR creata (o comando stampato), grafo aggiornato.

---

## Vincoli e divieti (riepilogo)

- NON toccare `approve_review` (righe 253-272): il doppio `async with` è intenzionale.
- NON modificare query, logica o formato del risultato di `get_review_analytics`.
- NON sistemare gli errori ruff preesistenti (~628) fuori dai file del task.
- NON committare segreti o file generati in `.agent/state/`.
- Docker deve essere attivo per i test in `tests/core/`.