# Migrazione ChromaDB → pgvector — Piano production-ready

## Executive summary — perché è urgente, non solo "pulizia architetturale"

Verificato riga per riga in `src/core/documenti/vector_store.py` e in `src/api/main.py`:

**C'è un leak/tampering cross-tenant attivo, non ipotetico.** Oggi tutta l'app è multi-tenant con RLS ovunque — tranne qui. `vector_store.py` usa **una singola collection ChromaDB globale** (`documenti_locale`), e nessuna delle funzioni (`cerca`, `elenco_fonti`, `elimina_documento`, `msg_ids_indicizzati`) filtra per `organization_id`. Le route in `main.py` (`carica_documento`, `carica_file_documento`, `elimina_documento_api`) sanno chi è l'utente (`require_ruolo`) ma non passano mai quell'informazione al livello di storage. Concretamente, oggi:
- Il retrieval RAG di un'organizzazione può restituire documenti caricati da un'altra org.
- `DELETE /api/documenti/{id}` può cancellare un documento di un'altra org, conoscendone/indovinandone l'id.

**Buona notizia che semplifica tutto**: l'infrastruttura DB per il fix esiste già, pronta, mai collegata. `document_chunks`/`documents` in `schema.sql` hanno già: `organization_id NOT NULL`, RLS attiva (`008_rls_hardening.sql`, `009_rls_write_check.sql`), FK CASCADE (`015_org_fk_strategy.sql`), un trigger di coerenza `check_chunk_org_consistency` che impedisce a un chunk di avere un `organization_id` diverso dal documento padre, e l'indice `hnsw (embedding vector_cosine_ops)` già creato (`024_hnsw_index.sql`). Il commento nello schema dice letteralmente *"pgvector, sostituisce ChromaDB"* — qualcuno l'aveva già progettato per questo, semplicemente il codice Python non è mai stato aggiornato per usarla.

`vector(384)` combacia esattamente con `paraphrase-multilingual-MiniLM-L12-v2` (il modello embedding già in uso, `normalize_embeddings=True` → coerente con `vector_cosine_ops`). Nessun cambio di modello richiesto.

**Conseguenza pratica**: questo non è un "riprogettare da zero", è "riscrivere un modulo Python per puntare al posto giusto". Il lavoro è più piccolo e più urgente di quanto suggerisse la roadmap originale.

---

## Architettura target

Mantengo la stessa interfaccia pubblica di `vector_store.py` (stessi nomi funzione) per minimizzare l'impatto sui chiamanti, ma con un cambio deliberato e non silenzioso: **ogni funzione pubblica prende `organization_id` come primo parametro obbligatorio.** Niente default che nasconda il problema — se un chiamante non lo passa, il codice non compila/non parte, non fallisce silenziosamente in produzione.

```
main.py (route documenti)
    -> passa organization_id da user["organization_id"] (gia' disponibile via require_ruolo)
    -> vector_store.py (stessa interfaccia pubblica, nuova implementazione)
    -> DocumentChunkRepository (nuovo, asyncpg, in src/core/db/repository.py o file dedicato)
    -> Postgres: documents + document_chunks (gia' pronte, RLS+trigger+hnsw)

qa_agent.py::rispondi()
    -> riceve organization_id da chi lo chiama (inbound_processor per il flusso WhatsApp reale)
    -> vector_store.cerca(organization_id, domanda, k)
```

---

## Interfacce (nuove firme — breaking change intenzionale)

```python
# src/core/documenti/vector_store.py — reimplementato su Postgres/pgvector

async def aggiungi(
    organization_id: str,
    document_id: str,
    chunks: list[str],
    metadati: list[dict] | None = None,
    on_progress: callable = None,
) -> int: ...

async def cerca(
    organization_id: str,
    query: str,
    k: int = 5,
) -> list[tuple[str, dict, float]]: ...

async def conteggio(organization_id: str) -> int: ...

async def elenco_fonti(organization_id: str) -> list[dict]: ...

async def elimina_documento(organization_id: str, documento_id: str) -> int: ...

async def msg_ids_indicizzati(organization_id: str) -> set[str]: ...
```

Nota: tutte diventano `async` (asyncpg è async-only) — i chiamanti in `main.py` che oggi le usano in endpoint sync vanno resi `async def` o usare `asyncio.to_thread`/adattamento coerente con quanto già fatto per `genera_risposta_recensione` nel lavoro recensioni.

`resetta()` va rimossa — era un helper solo per lo sviluppo locale con ChromaDB (cancellava la cartella `data/chroma/`); con Postgres il reset in test è già gestito da `reset_db` in `conftest.py`, non serve un equivalente in produzione.

---

## Fasi

**Fase 0 — Verifica dati reali da migrare (bloccante, serve una tua risposta)**
Prima di scrivere una riga, va chiarito: ci sono già documenti indicizzati in ChromaDB in produzione (cartella `data/chroma/` sul server) da portare via, o il sistema non è mai stato realmente usato (coerente con "RAG disconnesso" già segnalato nell'audit)? Se sì, serve uno script di migrazione one-shot che legga da ChromaDB e scriva su Postgres prima di spegnere il vecchio stack. Se no (probabile), si riparte pulito: i documenti originali restano nella tabella `documents`/nei file caricati, basta far ripartire l'indicizzazione.

**Fase 1 — Repository layer**
Nuovo metodo/i in `src/core/db/repository.py` (o modulo dedicato `src/core/documenti/repository.py`, coerente con come sono organizzati gli altri moduli):
- `insert_chunks(organization_id, document_id, chunks_con_embedding)` — batch insert, stessa logica a lotti da 100 già presente in `aggiungi()` originale, ma su `document_chunks`.
- `search_chunks(organization_id, query_embedding, k)` — `SELECT content, metadata, embedding <=> $1 AS distanza FROM document_chunks WHERE organization_id = $2 ORDER BY embedding <=> $1 LIMIT $3`. L'operatore `<=>` è cosine distance, coerente con l'indice hnsw già creato.
- `count_chunks(organization_id)`.
- `list_sources(organization_id)` — query aggregata per document_id/nome, equivalente a `elenco_fonti`.
- `delete_document(organization_id, document_id)` — `DELETE FROM documents WHERE id = $1 AND organization_id = $2` (il CASCADE già presente su `document_chunks.document_id` elimina i chunk automaticamente — non serve un secondo DELETE manuale, più atomico e meno codice).
- `list_indexed_msg_ids(organization_id)` — filtro su `metadata->>'tipo' = 'email'`.

**Fase 2 — Riscrittura `vector_store.py`**
Sostituisce il client ChromaDB con chiamate al repository sopra. Stesso comportamento osservabile (stessi nomi, stessa forma dei risultati) dove possibile, per minimizzare il diff nei chiamanti.

**Fase 3 — Aggiornamento chiamanti**
- `main.py`: `carica_documento`, `carica_file_documento`, `elimina_documento_api`, l'endpoint che chiama `conteggio()`/`elenco_fonti()` — passare `user["organization_id"]`, rendere le funzioni `async` dove serve.
- `qa_agent.py::rispondi()` — aggiungere parametro `organization_id`, propagato da chi la chiama (verificare se già chiamata da `inbound_processor.py` per il flusso WhatsApp reale, o solo da un endpoint dashboard/test — va tracciato esplicitamente durante l'esecuzione, non assunto).

**Fase 4 — Rimozione ChromaDB**
- `requirements.txt`: rimuovere `chromadb==1.1.1`.
- `.gitignore`: `data/chroma/` può restare (innocuo se non più popolato) o essere rimosso, non è urgente.
- Verifica che nessun altro punto del codice importi `chromadb` (fatto in fase di investigazione: unico punto era `vector_store.py`).

**Fase 5 — Test**
- Unit/integration su repository: insert + search restituisce i chunk giusti, **isolamento tra org** (test esplicito: chunk di org A non deve mai comparire in una query di org B — è il test che oggi manca e che avrebbe dovuto esistere fin dall'inizio).
- Test su `elimina_documento`: cancellazione da org sbagliata non deve toccare nulla (0 righe eliminate, non errore silenzioso).
- Test su `cerca()` con k maggiore dei risultati disponibili (non deve esplodere).
- Test end-to-end minimo: carica un documento, fai una domanda che dovrebbe trovarlo, verifica che compaia nei risultati.

---

## Casi limite

- **Org senza documenti indicizzati**: `cerca()` deve tornare lista vuota, non errore — il fallback "non ho questa informazione" (già previsto nella roadmap originale per il collegamento RAG) dipende da questo comportamento.
- **Trigger deferrable su `document_chunks`**: il trigger di coerenza organization_id è `DEFERRABLE INITIALLY DEFERRED` — significa che controlla la coerenza a fine transazione, non riga per riga. L'insert va fatto dentro una transazione esplicita che inserisce prima `documents` poi `document_chunks`, o il controllo potrebbe non scattare come previsto se le connessioni sono gestite in modo non transazionale (stesso tipo di errore già trovato e corretto su `approve_review` — vale la pena verificarlo esplicitamente con un test, non assumerlo.
- **Batch insert e limite parametri Postgres**: asyncpg supporta bene batch via `executemany`, ma con embedding a 384 dimensioni per riga, batch troppo grandi possono essere lenti — mantenere il batching a 100 già presente nell'originale è ragionevole, non serve reinventarlo.
- **Cancellazione documento con query di ricerca in corso**: accettabile inconsistenza temporanea (nessuna transazione distribuita necessaria), coerente con come il resto del sistema gestisce microscopiche race condition non critiche.

---

## Domanda 2 risolta (verificato, non ipotizzato)

`qa_agent.rispondi()` è chiamata **solo** da `POST /api/documenti/chiedi` in `main.py`, un endpoint dashboard protetto da `require_ruolo("owner","manager","staff")`. **Non** è mai chiamata da `inbound_processor.py` (il flusso di risposta WhatsApp reale ai clienti). Quindi:
- Il leak cross-tenant è reale e sfruttabile oggi, ma solo tramite un utente autenticato che usa quell'endpoint dashboard — non un cliente finale su WhatsApp.
- Il RAG non è ancora collegato al responder automatico (conferma l'item 11 della roadmap: "disconnesso"). Questa migrazione va fatta **prima** di collegarlo, altrimenti si collegherebbe un sistema già rotto lato tenant-isolation a un canale ben più esposto (chiunque scriva su WhatsApp, non solo utenti autenticati in dashboard).

## Domande aperte prima di eseguire

1. **Fase 0**: ci sono dati reali in `data/chroma/` in produzione da migrare, o si riparte da zero?
2. Vuoi che lo esegua io direttamente (il lavoro è contenuto: un file da riscrivere + wiring in 2-3 punti + repository), seguendo lo stesso ciclo TDD verificato-via-CI-reale usato per task9/10/11? O lo giri a DeepSeek e io faccio da revisore come per il resto?
