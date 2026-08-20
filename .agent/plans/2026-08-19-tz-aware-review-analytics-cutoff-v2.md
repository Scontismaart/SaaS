# Piano: TASK-044 — Cutoff timezone-aware in `get_review_analytics` + test DAVVERO discriminanti

- Complessità: M
- Approvato da: manager
- Data: 2026-08-19

> Nota: il task input non riportava un `task-id` esplicito; il manager assegna `TASK-044`.
> Re-run di TASK-043: il fix applicativo era corretto ma i test NON discriminavano
> (verdetto redteam `MAJOR_CONCERNS` in `.agent/reviews/2026-08-19-TASK-043-redteam.md`:
> 5/5 PASS anche ripristinando `datetime.utcnow()`). Il criterio di accettazione di QUESTA
> run è: **almeno un test fallisce col codice vecchio e passa col nuovo**.

## Contesto tecnico (verificato sul codice)

- `src/core/db/repository.py`, righe 274-319: `get_review_analytics(self, organization_id, giorni=90)`.
  - Riga 275: import locale `from datetime import datetime, timedelta` (DENTRO il corpo della funzione).
  - Riga 276: `cutoff = datetime.utcnow() - timedelta(days=giorni)` → finding ruff **DTZ003**.
  - Riga 277: `async with self.pool.acquire() as conn:` — la funzione acquisisce una connessione
    propria dal pool: un `SET TIME ZONE` fatto su un'altra connessione NON la influenza.
- `approve_review` (righe 253-272): NON va toccata (doppio `async with` intenzionale per il lock).
- `create_review` (righe 171-190): NON accetta `created_at` → nei test serve INSERT diretta.
- `reviews.created_at` è `TIMESTAMPTZ DEFAULT NOW()` (schema.sql riga 61); colonne aggiuntive
  `sentiment`, `categoria`, `is_anonymized` in `022_reviews_ext.sql`. Trigger `log_review_event`
  (023) scrive su `event_log` all'INSERT: innocuo per le query di analytics.
- `tests/core/conftest.py`: `pg_pool` usa `server_settings={"search_path": "public, extensions"}`
  (nessuna timezone fissata → dipende dal container). Fixture disponibili: `postgres_container`
  (session-scoped, espone `get_connection_url()`), `pg_pool`, `reset_db`, `repo`, `sample_org`.
- Stato attuale del working tree: pulito, HEAD su branch `ai/rendi-timezone-aware-il-calcolo-del-cutoff-in-get-review-ana`
  con il codice VECCHIO (`datetime.utcnow()`) e il file di test con i soli 2 test originali.
- `tests/core/test_repository_reviews.py`: `pytestmark = pytest.mark.usefixtures("reset_db")`.

---

## Fase 1 — Analisi

**Input:** task TASK-044, report redteam `.agent/reviews/2026-08-19-TASK-043-redteam.md`,
`src/core/db/repository.py` (righe 171-319), `tests/core/test_repository_reviews.py`,
`tests/core/conftest.py`, `src/core/db/schema.sql`, `src/core/db/migrations/022_reviews_ext.sql`.

**Azioni:**
1. Confermare che l'unico punto applicativo da modificare sia la riga 276 (cutoff) e l'import
   locale a riga 275 di `repository.py`. Nessun'altra riga del file va toccata.
2. Confermare il motivo per cui il patch su `src.core.db.repository.datetime` NON intercetta:
   l'import `from datetime import datetime, timedelta` è LOCALE al corpo della funzione e risolve
   alla classe stdlib `datetime.datetime`; il patch corretto è `unittest.mock.patch.object` sui
   metodi della classe stdlib (`now` e `utcnow`), oppure iniezione di parametro di test
   (scartata: modifica la firma pubblica). Scelta: `patch.object`.
3. Confermare che il pool del conftest non fissa la timezone (righe 39-44) e che quindi serve un
   pool DEDICATO con `server_settings={"search_path": "public, extensions", "timezone": "Europe/Rome"}`
   per la leva non-UTC a livello di pool (offset +2, `search_path` come nel conftest per trovare
   tabelle/estensioni). Il DSN si ricava da `postgres_container.get_connection_url().replace("+psycopg2", "")`.
4. Confermare le colonne per l'INSERT diretto su `reviews`: `id, organization_id, testo,
   valutazione_stelle, fonte, autore, created_at, sentiment, categoria` (schema.sql 53-62 +
   022_reviews_ext.sql). `is_anonymized` ha default FALSE → le review rientrano in `sentiment_trend`.
5. Verificare che Docker sia attivo prima di eseguire i test (`docker info`).

**Criteri di uscita:** individuati con precisione file/righe da toccare e i due meccanismi di
discriminazione (mock del tempo + sessione non-UTC a livello di pool); nessun'altra modifica
necessaria a query, logica o formato del risultato.

---

## Fase 2 — Progettazione

**Input:** esito Fase 1.

**Azioni:**
1. **Refactor minimo** in `src/core/db/repository.py`:
   - Riga 275: `from datetime import datetime, timedelta` → `from datetime import datetime, timedelta, timezone`.
   - Riga 276: `cutoff = datetime.utcnow() - timedelta(days=giorni)` → `cutoff = datetime.now(timezone.utc) - timedelta(days=giorni)`.
   - Nessun'altra modifica a query, logica o formato del risultato. NON toccare `approve_review`.
2. **Test discriminante** in `tests/core/test_repository_reviews.py` — DUE leve, entrambe obbligatorie:
   - **Leva 1 — Mock del tempo**: `patch.object(datetime, "now", return_value=FIXED)` e
     `patch.object(datetime, "utcnow", return_value=FIXED.replace(tzinfo=None))` con
     `FIXED = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)`. Il patch sui metodi della
     classe stdlib intercetta la chiamata interna perché l'import locale risolve alla stessa classe.
   - **Leva 2 — Sessione non-UTC a livello di POOL**: pool dedicato
     `asyncpg.create_pool(dsn, server_settings={"search_path": "public, extensions", "timezone": "Europe/Rome"})`,
     `CoreRepository(pool=pool_dedicato)` usato per INSERT e chiamata; `await pool.close()` in `finally`.
   - **Review a cavallo del confine**: `cutoff_atteso = FIXED - timedelta(days=giorni)` (aware UTC);
     (a) `cutoff_atteso - 1 minuto` → ESCLUSA; (b) `cutoff_atteso + 1 minuto` → INCLUSA.
   - **Assertions**: (a) NON compare in nessuno dei 4 bucket; (b) compare in tutti e 4.
   - **Meccanismo discriminante**: con sessione +2 e cutoff naive (codice vecchio), Postgres
     interpreta il naive come ora locale → confine effettivo a `cutoff_atteso - 2h` → la review (a)
     verrebbe erroneamente INCLUSA → il test FALLISCE col vecchio e PASSA col nuovo.
3. **TDD**: i test vengono scritti e fatti fallire PRIMA della modifica al repository.

**Criteri di uscita:** progetto approvato; nessuna modifica a `approve_review`; nessun refactoring
estraneo; il test è progettato per discriminare (rosso sul vecchio, verde sul nuovo).

---

## Fase 3 — Test (scrivere i test PRIMA del codice, TDD)

**Input:** `tests/core/test_repository_reviews.py` esistente, conftest con fixture
`postgres_container`, `reset_db`, `sample_org`.

**Azioni:**
1. Aggiungere gli import in testa al file (ordine isort: stdlib, terze parti, primo-party):
   ```python
   import uuid
   from datetime import datetime, timedelta, timezone
   from unittest.mock import patch

   import asyncpg
   import pytest

   from src.core.db.repository import CoreRepository
   ```
2. Aggiungere la costante e l'helper a livello modulo:
   ```python
   _FIXED_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


   async def _insert_review(repo, organization_id, *, created_at,
                            testo, valutazione_stelle, fonte, autore,
                            sentiment, categoria):
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
3. Aggiungere il test discriminante:
   ```python
   @pytest.mark.asyncio
   async def test_get_review_analytics_cutoff_is_timezone_aware(postgres_container, sample_org):
       """Discriminante: FALLISCE con datetime.utcnow(), PASSA con datetime.now(timezone.utc).

       Leve: (1) mock del tempo via patch.object sui metodi della classe stdlib datetime
       (l'import locale nel corpo di get_review_analytics risolve alla stessa classe);
       (2) pool dedicato con sessione timezone Europe/Rome (+2) a livello di POOL.
       """
       dsn = postgres_container.get_connection_url().replace("+psycopg2", "")
       pool = await asyncpg.create_pool(
           dsn=dsn,
           min_size=1,
           max_size=2,
           server_settings={"search_path": "public, extensions", "timezone": "Europe/Rome"},
       )
       try:
           repo_rome = CoreRepository(pool=pool)
           giorni = 90
           cutoff_atteso = _FIXED_NOW - timedelta(days=giorni)  # 2026-01-31 12:00 UTC

           # (a) 1 minuto PRIMA del cutoff -> deve essere ESCLUSA
           await _insert_review(
               repo_rome, sample_org["id"],
               created_at=cutoff_atteso - timedelta(minutes=1),
               testo="Fuori finestra", valutazione_stelle=1,
               fonte="fonte_a", autore="A", sentiment="negativo", categoria="categoria_a",
           )
           # (b) 1 minuto DOPO il cutoff -> deve essere INCLUSA
           await _insert_review(
               repo_rome, sample_org["id"],
               created_at=cutoff_atteso + timedelta(minutes=1),
               testo="Dentro finestra", valutazione_stelle=5,
               fonte="fonte_b", autore="B", sentiment="positivo", categoria="categoria_b",
           )

           with (
               patch.object(datetime, "now", return_value=_FIXED_NOW),
               patch.object(datetime, "utcnow", return_value=_FIXED_NOW.replace(tzinfo=None)),
           ):
               analytics = await repo_rome.get_review_analytics(sample_org["id"], giorni=giorni)

           trend = {r["sentiment"]: r["cnt"] for r in analytics["sentiment_trend"]}
           stars = {r["valutazione_stelle"]: r["cnt"] for r in analytics["star_distribution"]}
           cats = {r["categoria"]: r["cnt"] for r in analytics["category_distribution"]}
           sources = {r["fonte"]: r["cnt"] for r in analytics["source_distribution"]}

           # (b) DEVE comparire in tutti i bucket
           assert trend.get("positivo") == 1
           assert stars.get(5) == 1
           assert cats.get("categoria_b") == 1
           assert sources.get("fonte_b") == 1

           # (a) NON deve comparire in nessun bucket
           assert "negativo" not in trend
           assert 1 not in stars
           assert "categoria_a" not in cats
           assert "fonte_a" not in sources
       finally:
           await pool.close()
   ```
   Nota: le asserzioni contano per sentiment/stelle/categoria/fonte, NON per `DATE(created_at)`:
   così il test è immune alla fragilità del bucketing per giorno segnalata dal redteam (Finding 2).
4. Eseguire i test per osservare il rosso (PRIMA della modifica al repository):
   ```bash
   $env:PYTHONUTF8="1"; python -m pytest tests/core/test_repository_reviews.py -v --tb=short
   ```
   Atteso: i 2 test esistenti passano; il nuovo test discriminante FALLISCE (con `datetime.utcnow()`
   il cutoff naive viene interpretato in Europe/Rome → confine spostato di -2h → la review (a)
   risulta inclusa → `assert 1 not in stars` fallisce). Questo è il rosso TDD obbligatorio.

**Criteri di uscita:** il test discriminante è presente e osservato FALLIRE col codice vecchio
prima di toccare il codice applicativo.

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

**Criteri di uscita:** diff minimo: 2 righe modificate in `repository.py`; nessun altro file
applicativo toccato.

---

## Fase 5 — Verifica (comandi reali da `.agent/constitution.md`)

**Input:** implementazione completata.

**Azioni:**
1. Docker attivo:
   ```bash
   docker info
   ```
2. Test del file (Docker attivo):
   ```bash
   $env:PYTHONUTF8="1"; python -m pytest tests/core/test_repository_reviews.py -v --tb=short
   ```
   Atteso: tutti i test del file passano (2 esistenti + 1 nuovo discriminante).
3. **Verifica empirica di discriminazione (OBBLIGATORIA)** — il patch intercetta davvero e il
   test discrimina:
   ```bash
   git stash push -- src/core/db/repository.py
   $env:PYTHONUTF8="1"; python -m pytest tests/core/test_repository_reviews.py -v --tb=short
   git stash pop
   ```
   - Con `repository.py` ripristinato al codice vecchio (`datetime.utcnow()`): ALMENO il test
     discriminante deve FALLIRE (rosso).
   - Dopo `git stash pop` (fix ripristinato): il test deve tornare VERDE.
   - Nota: `git stash push -- <path>` stasha SOLO `repository.py`; i test restano sul working tree.
   - Se il test NON fallisce col codice vecchio, il requisito NON è soddisfatto: avviare Fase 6.
4. Test completi del repo (Docker attivo):
   ```bash
   $env:PYTHONUTF8="1"; python -m pytest -v --tb=short
   ```
   Atteso: nessuna regressione.
5. Lint sui soli file del task (i 3 errori preesistenti I001/SIM117/B017 restano fuori scope):
   ```bash
   python -m ruff check src/core/db/repository.py tests/core/test_repository_reviews.py
   ```
   Atteso: nessun errore NUOVO (in particolare DTZ003 eliminato; eventuale I001 nuovo sul file di
   test va corretto riordinando gli import).
6. Format sui soli file del task:
   ```bash
   python -m ruff format src/core/db/repository.py tests/core/test_repository_reviews.py
   ```

**Criteri di uscita:** test verdi col nuovo codice, ALMENO un test rosso col codice vecchio
(verifica empirica documentata), lint pulito sui file toccati, nessuna regressione.

---

## Fase 6 — Riparazione (se i test falliscono, max 3 iterazioni)

**Input:** esito Fase 5 (eventuali fallimenti).

**Azioni:**
1. Iterazione 1: analizzare il fallimento (log pytest `--tb=short`), correggere, rieseguire i
   test del file.
2. Iterazione 2: se ancora rosso, ripetere analisi + correzione + riesecuzione.
3. Iterazione 3: ultimo tentativo; se ancora rosso, fermarsi e segnalare all'operatore (nessun commit).
4. Casi noti da verificare in diagnosi:
   - Se il test discriminante PASSA anche col codice vecchio → il mock non intercetta o la sessione
     non è +2: verificare che `patch.object` agisca sulla classe stdlib (non su
     `src.core.db.repository.datetime`) e che il pool dedicato abbia davvero `timezone: Europe/Rome`
     (provare con `SHOW timezone` su una connessione del pool dedicato).
   - Se il test fallisce anche col codice nuovo → verificare che `created_at` aware venga codificato
     come timestamptz da asyncpg e che `reset_db`/`sample_org` girino prima del pool dedicato.
   - Se il fallimento riguarda il setup Docker/container: verificare `docker info` e riprovare;
     non "sistemare" i test per farli passare a forza.
5. Dopo ogni correzione, ripetere la verifica empirica di discriminazione (punto 3 di Fase 5).

**Criteri di uscita:** test verdi col nuovo codice e rossi col vecchio entro 3 iterazioni, oppure
stop con segnalazione all'operatore.

---

## Fase 7 — Rilascio (commit, branch `ai/<slug>`, PR)

**Input:** esito Fase 5/6 (verde + discriminazione verificata).

**Azioni:**
1. Branch: si è già sul branch `ai/rendi-timezone-aware-il-calcolo-del-cutoff-in-get-review-ana`
   (verificare con `git status`); in alternativa crearlo:
   ```bash
   git checkout -b ai/tz-aware-review-analytics-cutoff-v2
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
   git commit -m "test(reviews): test discriminante sul cutoff timezone-aware (mock tempo + sessione +2)"
   ```
   (oppure un unico commit convenzionale).
4. PR tramite `gh` (se disponibile):
   ```bash
   gh pr create --title "fix(reviews): cutoff timezone-aware in get_review_analytics (test discriminanti)" --body "TASK-044: sostituisce datetime.utcnow() (DTZ003) con datetime.now(timezone.utc) e aggiunge un test che FALLISCE col codice vecchio e PASSA col nuovo (mock del tempo via patch.object + pool dedicato con timezone Europe/Rome + review al confine della finestra)."
   ```
   Se `gh` non è disponibile, stampare il comando `gh pr create` da eseguire manualmente.
5. Aggiornare il grafo della conoscenza (regola AGENTS.md):
   ```bash
   graphify update .
   ```

**Criteri di uscita:** branch `ai/<slug>` con commit convenzionali, PR creata (o comando stampato),
grafo aggiornato.

---

## Vincoli e divieti (riepilogo)

- NON toccare `approve_review` (righe 253-272): il doppio `async with` è intenzionale.
- NON modificare query, logica o formato del risultato di `get_review_analytics`.
- NON introdurre dipendenze nuove: solo stdlib (`unittest.mock`, `datetime`), `asyncpg` (già
  presente), pytest e le fixture esistenti.
- NON usare `create_review` per le review con `created_at` esplicito: INSERT diretta su `reviews`.
- NON sistemare gli errori ruff preesistenti (~628) fuori dai file del task.
- NON committare segreti o file generati in `.agent/state/`.
- Docker deve essere attivo per i test in `tests/core/`.
- La verifica empirica di discriminazione (rosso sul vecchio, verde sul nuovo) è OBBLIGATORIA e va
  riportata nel report finale con l'esito di entrambe le esecuzioni.