Rendi timezone-aware il calcolo del cutoff in `get_review_analytics` in `src/core/db/repository.py` (riga 274 circa) e aggiungi test dedicati.

Contesto: la funzione usa `datetime.utcnow()` (riga 276), deprecato in Python 3.12 (finding ruff DTZ003). Deve usare `datetime.now(timezone.utc)`. La colonna `created_at` di `reviews` e' TIME WITH TIME ZONE: il cutoff va calcolato in UTC aware per un confronto corretto. La funzione oggi non ha test.

Requisiti (TDD: prima i test, poi la modifica):
- Refactor minimo: sostituire `datetime.utcnow()` con `datetime.now(timezone.utc)` e aggiornare di conseguenza l'import nella firma `from datetime import datetime, timedelta` (aggiungere `timezone`). Nessun altro cambiamento alla logica, alle query o al formato del risultato.
- Non toccare `approve_review` (il doppio `async with` intorno a riga 257-258 e' intenzionale, serve per il lock transazionale).
- Aggiungere test in `tests/core/test_repository_reviews.py` che usino le fixture `repo` e `sample_org` del conftest (PostgresContainer). I test devono:
  1. creare review con `created_at` esplicito (passando la data nella insert di test o tramite un helper) dentro la finestra degli ultimi N giorni e verificare che `get_review_analytics` le includa nei vari bucket (almeno `sentiment_trend` e `star_distribution`);
  2. creare una review con `created_at` piu' vecchio del cutoff e verificare che venga esclusa;
  3. verificare che il cutoff sia timezone-aware: passare un cutoff manuale/forzato e confermare che il confronto funzioni con timezone diverse (es. creare review con `created_at` a mezzanotte UTC vs mezzanotte +2 e verificare che la finestra non sposti i conteggi).
- Se serve un aiuto per inserire `created_at` espliciti nei test, guarda come lo schema `reviews` definisce la colonna (per le INSERT di test basta specificare `created_at`).
- Verifica: esegui `python -m pytest tests/core/test_repository_reviews.py -v` (Docker attivo) finche' tutti i test del file passano, incluso il nuovo gruppo.