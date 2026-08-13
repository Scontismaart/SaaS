# Rimozione ChromaDB, route documenti su pgvector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare `vector_store.py` (ChromaDB), portare le route documenti al pattern consolidato `_get_repo(request)` + `user["organization_id"]` su Postgres/pgvector, chiudendo il leak/tampering cross-tenant attivo.

**Architecture:** Le route `/api/documenti/*` in `main.py` passano da chiamate alla collezione globale ChromaDB a chiamate dirette a `CoreRepository` (metodi `create_document`, `add_chunk`, `search_similar`, `list_documents` già scritti e testati). Il repository layer è già completo — mancano solo `count_chunks`, `list_sources`, `delete_document`. `qa_agent.rispondi()` diventa `async` e riceve `organization_id` obbligatorio.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, pgvector (`vector(384)` + indice hnsw `024`), pytest-asyncio, testcontainers (`pgvector/pgvector:0.7.4-pg16`).

## Global Constraints

- Verifica vera = CI reale (GitHub Actions), non esecuzione locale. Push + PR verso main, leggere il conteggio pass/fail per intero prima di dire "fatto".
- Numerazione migration: sempre dal numero più alto su `origin/main` (= **026** oggi). Qui NON serve una migration — lo schema esiste già.
- Branch nuovo, esplicito, da `origin/main` aggiornato: `task12/pgvector-documenti` (già creato).
- NON toccare i metodi repo esistenti `create_document`, `add_chunk`, `search_similar`, `list_documents` (già testati) se non necessario.
- Fase 0: NON migrare dati — `data/chroma/` contiene solo notifiche Gmail, si riparte puliti. `scripts/migrate_chromadb_to_pgvector.py` resta come utility futura, non va lanciato.
- `msg_ids_indicizzati()` e `resetta()` sono orfani: rimuoverli (insieme al modulo), non migrarli.
- Embedded model invariato: `paraphrase-multilingual-MiniLM-L12-v2` (384 dim), `normalize_embeddings=True`.

---

### Task 1: Metodi repository mancanti (`count_chunks`, `list_sources`, `delete_document`)

**Files:**
- Modify: `src/core/db/repository.py` (aggiungere dopo `list_documents`, ~riga 404)
- Test: `tests/core/test_repository_documents.py`

**Interfaces:**
- Consumes: `CoreRepository(pool)` — pattern `async with self.pool.acquire() as conn`
- Produces:
  - `async def count_chunks(self, organization_id) -> int`
  - `async def list_sources(self, organization_id) -> list[dict]` — ogni dict con chiavi `id, nome, tipo, fonte, caricato_il, chunk` (conteggio chunk)
  - `async def delete_document(self, organization_id, document_id) -> int` (righe eliminate; il CASCADE su `document_chunks.document_id` elimina i chunk)

- [ ] **Step 1: Scrivere i test fallenti**

```python
# in tests/core/test_repository_documents.py (append)

@pytest.mark.asyncio
async def test_count_chunks(repo, sample_org):
    doc = await repo.create_document(organization_id=sample_org["id"], nome="doc.pdf", tipo="upload")
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=0, content="c1", embedding=[0.1] * 384)
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=1, content="c2", embedding=[0.2] * 384)
    assert await repo.count_chunks(sample_org["id"]) == 2
    assert await repo.count_chunks(other_org["id"]) == 0


@pytest.mark.asyncio
async def test_list_sources_groups_by_document(repo, sample_org):
    doc = await repo.create_document(organization_id=sample_org["id"], nome="menu.pdf", tipo="upload", fonte="dashboard")
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=0, content="c1", embedding=[0.1] * 384)
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=1, content="c2", embedding=[0.2] * 384)
    fonti = await repo.list_sources(sample_org["id"])
    assert len(fonti) == 1
    assert fonti[0]["nome"] == "menu.pdf"
    assert fonti[0]["chunk"] == 2
    assert str(fonti[0]["id"]) == str(doc["id"])


@pytest.mark.asyncio
async def test_delete_document_org_scoped(repo, sample_org, other_org):
    doc = await repo.create_document(organization_id=sample_org["id"], nome="doc.pdf", tipo="upload")
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=0, content="c1", embedding=[0.1] * 384)
    # org sbagliata non tocca nulla
    assert await repo.delete_document(other_org["id"], doc["id"]) == 0
    # org giusta elimina documento + chunk via cascade
    assert await repo.delete_document(sample_org["id"], doc["id"]) == 1
    assert await repo.count_chunks(sample_org["id"]) == 0
```

- [ ] **Step 2: Verificare che falliscano**

Run: `python -m pytest tests/core/test_repository_documents.py -q`
Expected: `AttributeError` (metodi non esistenti)

- [ ] **Step 3: Implementare i metodi**

```python
# in src/core/db/repository.py, dopo list_documents

    async def count_chunks(self, organization_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM document_chunks WHERE organization_id = $1",
                organization_id,
            )
            return row["n"]

    async def list_sources(self, organization_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT d.id, d.nome, d.tipo, d.fonte, d.caricato_il,
                       COUNT(dc.id) AS chunk
                FROM documents d
                LEFT JOIN document_chunks dc ON dc.document_id = d.id
                WHERE d.organization_id = $1
                GROUP BY d.id
                ORDER BY d.caricato_il DESC, d.nome
            """, organization_id)
            return [dict(r) for r in rows]

    async def delete_document(self, organization_id, document_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                DELETE FROM documents WHERE id = $1 AND organization_id = $2
                RETURNING id
            """, document_id, organization_id)
            return 1 if row else 0
```

- [ ] **Step 4: Verificare che passino**

Run: `python -m pytest tests/core/test_repository_documents.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/core/test_repository_documents.py src/core/db/repository.py
git commit -m "feat(repo): count_chunks/list_sources/delete_document per route documenti pgvector"
```

---

### Task 2: `qa_agent.rispondi()` async con `organization_id`

**Files:**
- Modify: `src/core/documenti/qa_agent.py`
- Test: `tests/core/test_qa_agent.py` (nuovo)

**Interfaces:**
- Consumes: `repo.search_similar(organization_id, embedding, k)` → lista dict con `content`, `metadata`, `document_name`, `distance`; `vettorizza(testi, tipo="query")` da `src.core.documenti.embeddings`
- Produces: `async def rispondi(organization_id: str, domanda: str, repo, k: int = 5) -> dict` — dict con chiavi `risposta`, `fonti`

- [ ] **Step 1: Scrivere il test fallente**

```python
# tests/core/test_qa_agent.py
import pytest
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.asyncio

class _FakeLLM:
    def call(self, prompt):
        return "La pizza margherita costa 8 euro."

async def test_rispondi_richiede_organization_id():
    repo = AsyncMock()
    repo.search_similar = AsyncMock(return_value=[{
        "content": "Pizza margherita: 8 euro",
        "document_name": "menu.pdf",
        "metadata": {"fonte": "menu.pdf"},
        "distance": 0.1,
    }])
    from src.core.documenti.qa_agent import rispondi
    with patch("src.core.documenti.qa_agent.vettorizza",
               return_value=[[0.1] * 384]), \
         patch("src.core.documenti.qa_agent.crea_llm", return_value=_FakeLLM()):
        out = await rispondi("org-1", "quanto costa la pizza?", repo, k=5)
    repo.search_similar.assert_awaited_once()
    assert out["risposta"] == "La pizza margherita costa 8 euro."
    assert out["fonti"][0]["documento"] == "menu.pdf"

async def test_rispondi_senza_risultati_non_chiama_llm():
    repo = AsyncMock()
    repo.search_similar = AsyncMock(return_value=[])
    from src.core.documenti.qa_agent import rispondi
    with patch("src.core.documenti.qa_agent.vettorizza",
               return_value=[[0.1] * 384]), \
         patch("src.core.documenti.qa_agent.crea_llm") as mock_llm:
        out = await rispondi("org-1", "quanto costa?", repo)
    mock_llm.assert_not_called()
    assert out["fonti"] == []
```

- [ ] **Step 2: Verificare che fallisca**

Run: `python -m pytest tests/core/test_qa_agent.py -q`
Expected: FAIL (firma attuale `rispondi(domanda, k)` sync, chiama `cerca` da vector_store)

- [ ] **Step 3: Riscrivere `qa_agent.py`**

```python
from src.core.llm_config import crea_llm
from src.core.documenti.embeddings import vettorizza


async def rispondi(organization_id: str, domanda: str, repo, k: int = 5) -> dict:
    q_emb = vettorizza([domanda], tipo="query")[0]
    risultati = await repo.search_similar(organization_id, q_emb, k)

    if not risultati:
        return {
            "risposta": "Non ho trovato documenti rilevanti per rispondere alla domanda.",
            "fonti": [],
        }

    contesto = "\n\n".join(f"-- Documento --\n{r['content']}" for r in risultati)

    fonti_dict = {}
    for r in risultati:
        nome = (r.get("document_name") or (r.get("metadata") or {}).get("fonte") or "documento").strip()
        if not nome:
            nome = "documento"
        if nome not in fonti_dict or r["distance"] < fonti_dict[nome]["score"]:
            fonti_dict[nome] = {"documento": nome, "score": round(r["distance"], 4)}
    fonti = sorted(fonti_dict.values(), key=lambda f: f["score"])

    prompt = (
        "Sei l'assistente knowledge base di un ristorante. Il tuo compito e' estrarre "
        "informazioni operative da menu, lista allergeni, carta vini e documenti simili, "
        "basandoti esclusivamente sui documenti forniti qui sotto.\n\n"
        "Linee guida:\n"
        "- Rispondi nella stessa lingua della domanda\n"
        "- Basati SOLO sui documenti forniti di seguito\n"
        "- Se i documenti non contengono la risposta, dillo chiaramente\n"
        "- Per allergie o intolleranze, fornisci solo informazioni presenti nei documenti e invita sempre a confermare con lo staff\n"
        "- Organizza la risposta in modo chiaro e leggibile\n"
        "- Alla fine, elenca le fonti che hai usato\n\n"
        f"Documenti disponibili:\n{contesto}\n\n"
        f"Domanda: {domanda}"
    )

    try:
        llm = crea_llm(temperature=0.15)
        risposta_raw = llm.call(prompt)
        risposta = str(risposta_raw).strip() if risposta_raw else (
            "Impossibile generare una risposta."
        )
    except Exception as e:
        print(f"[qa_agent] Errore LLM: {e}")
        risposta = (
            "Non ho potuto analizzare i documenti in questo momento. "
            "Riprova più tardi."
        )

    return {"risposta": risposta, "fonti": fonti}
```

- [ ] **Step 4: Verificare che passi**

Run: `python -m pytest tests/core/test_qa_agent.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/documenti/qa_agent.py tests/core/test_qa_agent.py
git commit -m "refactor(qa_agent): rispondi async con organization_id su pgvector"
```

---

### Task 3: Route documenti su `_get_repo` + `user["organization_id"]`

**Files:**
- Modify: `src/api/main.py` (righe ~35, ~545-606)
- Test: `tests/core/test_documenti_routes.py` (nuovo)

**Interfaces:**
- Consumes: `get_repo(request)` (già importato da `src.core.auth.dependencies`, riga 70); `user["organization_id"]` (popolato da `require_ruolo` → `get_organization_context`); metodi repo Task 1; `rispondi` Task 2; `vettorizza`; `chunk_testo`; `estrai_testo`
- Produces: stessi endpoint e formati di risposta di oggi (`/api/documenti/chiedi`, `/conteggio`, `/elenco`, `/carica`, `/carica-file`, `DELETE /{id}`), ma org-scoped e async

- [ ] **Step 1: Scrivere i test fallenti** (vedi Test documenti qui sotto — il file completo è nello Step 3 del Task; qui si scrive il fixture async_client e i test cross-tenant)

- [ ] **Step 2: Verificare che falliscano**

Run: `python -m pytest tests/core/test_documenti_routes.py -q`
Expected: FAIL (route chiamano ancora `aggiungi`/`cerca`/`elimina_documento` di vector_store; async-client non collegato)

- [ ] **Step 3: Riscrivere le route in `main.py`**

Rimuovere riga 35:
```python
from src.core.documenti.vector_store import aggiungi, conteggio, elenco_fonti, elimina_documento
```

Sostituire le route documenti (righe 545-606) con:

```python
@app.post("/api/documenti/chiedi", response_model=RispostaDocumento)
async def chiedi_documenti(domanda: DomandaInput, request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    repo = get_repo(request)
    return await rispondi(user["organization_id"], domanda.domanda, repo, k=domanda.k)


@app.get("/api/documenti/conteggio")
async def conteggio_documenti(request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    repo = get_repo(request)
    return {"chunk_indicizzati": await repo.count_chunks(user["organization_id"])}


@app.get("/api/documenti/elenco")
async def elenco_documenti(request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    repo = get_repo(request)
    return {"documenti": await repo.list_sources(user["organization_id"])}


@app.post("/api/documenti/carica")
async def carica_documento(doc: CaricaDocumentoInput, request: Request, user: dict = Depends(require_ruolo("owner", "manager"))):
    if not doc.testo.strip():
        raise HTTPException(status_code=400, detail="Testo vuoto.")

    repo = get_repo(request)
    chunks = chunk_testo(doc.testo)
    if not chunks:
        raise HTTPException(status_code=400, detail="Testo senza contenuto indicizzabile.")

    record = await repo.create_document(user["organization_id"], doc.nome, tipo="upload", fonte="dashboard")
    embeds = vettorizza(chunks, tipo="passage")
    for i, (chunk, emb) in enumerate(zip(chunks, embeds)):
        await repo.add_chunk(
            user["organization_id"], record["id"], i, chunk, emb,
            {"fonte": doc.nome, "tipo": "upload", "document_id": str(record["id"])},
        )
    return {"detail": f"Indicizzati {len(chunks)} chunk da '{doc.nome}'.", "indicizzati": len(chunks), "id": str(record["id"])}


@app.post("/api/documenti/carica-file")
async def carica_file_documento(request: Request, file: UploadFile = File(...), user: dict = Depends(require_ruolo("owner", "manager"))):
    nome = file.filename or "documento"
    contenuto = await file.read()
    if not contenuto:
        raise HTTPException(status_code=400, detail="Il file è vuoto.")
    if len(contenuto) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Il file supera il limite di 20 MB.")
    try:
        testo = estrai_testo(contenuto, nome, file.content_type or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repo = get_repo(request)
    chunks = chunk_testo(testo)
    if not chunks:
        raise HTTPException(status_code=400, detail="Nessun testo indicizzabile estratto dal file.")

    record = await repo.create_document(user["organization_id"], nome, tipo="documento", fonte=nome)
    embeds = vettorizza(chunks, tipo="passage")
    for i, (chunk, emb) in enumerate(zip(chunks, embeds)):
        await repo.add_chunk(
            user["organization_id"], record["id"], i, chunk, emb,
            {"fonte": nome, "tipo": "documento", "document_id": str(record["id"])},
        )
    return {"detail": f"Indicizzati {len(chunks)} chunk da '{nome}'.", "indicizzati": len(chunks), "nome": nome, "id": str(record["id"])}


@app.delete("/api/documenti/{documento_id}")
async def elimina_documento_api(documento_id: str, request: Request, user: dict = Depends(require_ruolo("owner", "manager"))):
    repo = get_repo(request)
    eliminati = await repo.delete_document(user["organization_id"], documento_id)
    if not eliminati:
        raise HTTPException(status_code=404, detail="Documento non trovato.")
    await _audit(request, user, "documento_eliminato", target_table="documents", details={"documento_id": documento_id, "chunk_eliminati": eliminati})
    return {"detail": "Documento rimosso dalla knowledge base.", "chunk_eliminati": eliminati}
```

Nota: `carica_file_documento` oggi ha `file: UploadFile = File(...)` — serve aggiungere `request: Request`. Per le regole Python i parametri senza default devono precedere quelli con default, quindi `request: Request` va prima di `file: UploadFile = File(...)`.

- [ ] **Step 4: Scrivere/verificare i test route documenti**

```python
# tests/core/test_documenti_routes.py
import os
import uuid
import pytest
import httpx
from unittest.mock import AsyncMock, patch

API_KEY = "test-api-key-12345"

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def set_env():
    os.environ["DATABASE_URL"] = ""
    os.environ["API_KEY_SERVICE"] = API_KEY


@pytest.fixture
async def async_client(repo, pg_pool):
    from src.api.main import app
    app.state.repo = repo
    app.state.pool = pg_pool
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _headers(org_id):
    return {"X-API-Key": API_KEY, "X-Organization-Id": str(org_id)}


class _FakeLLM:
    def call(self, prompt):
        return "La pizza margherita costa 8 euro."


async def test_chiedi_no_auth(async_client):
    resp = await async_client.post("/api/documenti/chiedi", json={"domanda": "quanto costa?"})
    assert resp.status_code == 401


async def test_carica_e_chiedi_org_scoped(async_client, sample_org, other_org):
    with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
        resp = await async_client.post("/api/documenti/carica", json={
            "testo": "Pizza margherita: 8 euro. Pizza diavola: 9 euro.",
            "nome": "menu.pdf",
        }, headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    doc_id = resp.json()["id"]

    # elenco e conteggio visibili per l'org giusta, vuoti per l'altra
    elenco = await async_client.get("/api/documenti/elenco", headers=_headers(sample_org["id"]))
    assert elenco.status_code == 200
    assert any(d["id"] == doc_id for d in elenco.json()["documenti"])
    altra = await async_client.get("/api/documenti/elenco", headers=_headers(other_org["id"]))
    assert altra.status_code == 200
    assert all(d["id"] != doc_id for d in altra.json()["documenti"])

    # chiedi con LLM mockato
    with patch("src.core.documenti.qa_agent.vettorizza", return_value=[[0.1] * 384]), \
         patch("src.core.documenti.qa_agent.crea_llm", return_value=_FakeLLM()):
        r = await async_client.post("/api/documenti/chiedi", json={"domanda": "quanto costa la pizza?"},
                                    headers=_headers(sample_org["id"]))
    assert r.status_code == 200
    assert r.json()["risposta"] == "La pizza margherita costa 8 euro."


async def test_delete_cross_tenant_non_tocca_org_altrui(async_client, sample_org, other_org):
    with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
        resp = await async_client.post("/api/documenti/carica", json={
            "testo": "Documento segreto dell'org A",
            "nome": "segreti.txt",
        }, headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    doc_id = resp.json()["id"]

    # org B non può cancellare il documento di org A
    resp_b = await async_client.delete(f"/api/documenti/{doc_id}", headers=_headers(other_org["id"]))
    assert resp_b.status_code == 404

    # org A può
    resp_a = await async_client.delete(f"/api/documenti/{doc_id}", headers=_headers(sample_org["id"]))
    assert resp_a.status_code == 200
```

- [ ] **Step 5: Verificare che passino**

Run: `python -m pytest tests/core/test_documenti_routes.py tests/core/test_repository_documents.py tests/core/test_qa_agent.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/main.py tests/core/test_documenti_routes.py
git commit -m "feat(api): route documenti org-scoped su pgvector (fix leak cross-tenant)"
```

---

### Task 4: Rimozione ChromaDB (`vector_store.py`, import residui, requirements)

**Files:**
- Delete: `src/core/documenti/vector_store.py`
- Modify: `requirements.txt` (riga 4: rimuovere `chromadb==1.1.1`)
- Test: suite completa

- [ ] **Step 1: Verificare che non restino import di vector_store/chromadb**

Run: `python -c "import ast, glob, sys; pats=['vector_store','chromadb']; bad=[f for f in glob.glob('src/**/*.py', recursive=True)+glob.glob('tests/**/*.py', recursive=True) if any(p in open(f,encoding='utf-8').read() for p in pats)]; print('residui:', bad) if bad else print('OK nessun residuo')"`
Expected: OK (unico residuo lecito: `scripts/migrate_chromadb_to_pgvector.py` che usa chromadb come utility futura)

- [ ] **Step 2: Eliminare `vector_store.py` e rimuovere chromadb da requirements**

```bash
git rm src/core/documenti/vector_store.py
```

`requirements.txt`: rimuovere la riga `chromadb==1.1.1`.

- [ ] **Step 3: Verifica import + suite completa**

Run: `python -m py_compile src/api/main.py src/core/documenti/qa_agent.py`
Run: `python -m pytest -q`
Expected: tutta la suite verde (task route + repo + qa_agent inclusi)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: rimuovi chromadb e vector_store.py (dual-stack risolto, ora solo pgvector)"
```

---

### Task 5: Verifica finale + PR

- [ ] **Step 1: ruff sui file toccati**

Run: `ruff check src/api/main.py src/core/documenti/qa_agent.py src/core/db/repository.py tests/core/test_documenti_routes.py tests/core/test_qa_agent.py tests/core/test_repository_documents.py`
Expected: nessun errore NUOVO rispetto alla base (gli E402/F401 preesistenti di main.py restano).

- [ ] **Step 2: Push e PR verso main**

```bash
git push -u origin task12/pgvector-documenti
```
Creare PR verso `main` (replicare formato dei PR precedenti: titolo + corpo con riepilogo e stato test).

- [ ] **Step 3: Verifica CI reale**

Scaricare i log del run CI, leggere il conteggio pass/fail per intero. Solo con run verde e conteggio letto → dichiarare "fatto".

---

## Self-Review

- **Spec coverage:** Task 1 = metodi repo mancanti; Task 2 = qa_agent async con org; Task 3 = wiring route + test cross-tenant sulle route; Task 4 = rimozione vector_store/chromadb/import/orfani; Task 5 = verifica CI. Tutti i punti del prompt coperti.
- **Placeholder scan:** nessun TBD/TODO; ogni step ha codice concreto.
- **Type consistency:** `count_chunks(organization_id)->int`, `list_sources(organization_id)->list[dict]`, `delete_document(organization_id, document_id)->int` coerenti tra Task 1 e Task 3. `rispondi(organization_id, domanda, repo, k)->dict` coerente tra Task 2 e Task 3. `search_similar` ritorna dict con `content/document_name/metadata/distance` (verificato a riga 379-396 di repository.py).
