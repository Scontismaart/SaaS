# Costituzione dell'infrastruttura multi-agente

Questo documento definisce le regole vincolanti per tutti gli agenti che lavorano su questo
repository. Ogni agente DEVE leggerlo prima di agire. Nessuna eccezione.

## Regole trasversali

- Lingua di lavoro: **italiano** (commenti, report, messaggi di commit se possibile).
- Mai inserire segreti reali (chiavi, token, password) in file, log o commit.
- Mai modificare file applicativi esistenti se il task non lo richiede espressamente.
- Rispettare la struttura di directory definita in `.agent/`:
  - `backlog/` — task in attesa o futuri
  - `plans/` — piani approvati o proposti
  - `reviews/` — report di revisione (redteam)
  - `decisions/` — decisioni dell'arbitro
  - `state/` — stato corrente del lavoro (branch, step in corso)
  - `memory/lessons/` — lezioni apprese (LESSON-NNN-*.md)
  - `memory/failures/` — fallimenti e cause (FAILURE-NNN-*.md)
  - `evaluations/` — valutazioni di tentativi/attività
  - `prompts/` — prompt dei ruoli agent

## Ruleset A — Agent implementer

1. Lavora SOLO a partire da un piano approvato (presente in `.agent/plans/`). Se non c'è un
   piano approvato, fermati e chiedi al manager di crearne uno.
2. Pratica il TDD: scrivi/aggiorna prima i test, poi l'implementazione.
3. Modifica solo i file strettamente necessari al task. Nessun refactoring estraneo.
4. Dopo ogni modifica, esegui la verifica prevista dal repo (test + lint). Non dichiarare
   completo un lavoro non verificato.
5. Se i test falliscono, NON ignorarli: avvia il repair loop descritto in Ruleset B.
6. Non committare mai segreti, dati reali di produzione o file generati in `.agent/state/`.
7. Il report finale deve includere: file toccati, comandi di verifica eseguiti, esito.
8. Chiedi sempre la modifica dei file applicativi solo quando il task lo prevede.

## Ruleset B — Manager e arbitro

1. Il manager pianifica e approva i piani per tutti i livelli di complessità tranne `S`
   (solo implementer, nessuna pianificazione manageriale).
2. Il redteam rivisita in modo avversario (sicurezza, edge case, qualità) e scrive un report
   in `.agent/reviews/`.
3. L'arbitro decide tra `continue`, `redo`, `stop` in base a: piano approvato, log dei
   tentativi e report redteam. La decisione va salvata in `.agent/decisions/`.
4. Il repair loop (max 3 iterazioni) si applica a OGNI livello di complessità quando i test
   falliscono — non solo a L/XL. Ogni iterazione: analizza il fallimento, corregge,
   riesegue i test.
5. Al termine: crea un branch `ai/<task-slug>`, commit convenzionali, e PR tramite `gh`
   (se disponibile) oppure stampa il comando `gh pr create` da eseguire manualmente.

## Comandi reali del repository

Stack: Python 3.12 + FastAPI + pytest. Non inventare comandi: usa questi.

- **Test** (tutti i test):
  ```bash
  PYTHONUTF8=1 python -m pytest -v --tb=short
  ```
  Nota: i test in `tests/core/` richiedono Docker (testcontainers pgvector). Assicurati che
  Docker sia attivo prima di eseguirli.
- **Test** (solo unit, senza Docker):
  ```bash
  PYTHONUTF8=1 python -m pytest tests/unit -v --tb=short
  ```
- **Lint**:
  ```bash
  python -m ruff check src/ tests/
  ```
  Nota: il repo ha ~628 errori preesistenti con ruff 0.16.1 (la CI usa `continue-on-error`).
  NON sistemarli se non richiesti; i file nuovi/modificati devono però passare.
- **Typecheck**: non configurato (nessuno strumento installato). N/A.
- **Build**: non configurato (progetto Python senza step di build). N/A.
- **Format**: `python -m ruff format` (da usare solo sui file del task).

Su Windows, PowerShell: `$env:PYTHONUTF8="1"; python -m pytest -v --tb=short`
