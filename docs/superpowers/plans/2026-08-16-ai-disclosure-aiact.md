# AI Act Disclosure al Primo Contatto — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementare l'obbligo di trasparenza AI Act art. 50(1) per il canale WhatsApp: il primo messaggio automatico ricevuto da ciascun contatto inizia con la disclosure "sono un assistente automatico di IA", mai piu' per quel contatto, con escape hatch "OPERATORE" che forza l'escalation a un umano.

**Architecture:** Colonna `ai_disclosure_sent_at` su `contacts` (migration 029). Metodo atomico e idempotente `mark_ai_disclosure_sent(contact_id)` nel WhatsApp Repository (stesso pattern di `try_mark_replied`). Helper `decorate_with_disclosure(...)` in `inbound_processor.py` che prepone la disclosure solo quando vince il primo UPDATE concorrente. Nuovo check `check_human_request(text)` nel `WhatsAppService` (pattern di `check_opt_out`) con ramo dedicato nel pipeline inbound che invia un messaggio di attesa e fa escalation HITL.

**Tech Stack:** Python 3.x, asyncpg, FastAPI, pytest (testcontainers postgres:16 nei test con DB), CrewAI/OpenRouter (non toccati).

## Global Constraints

- Nuova migrazione: `src/core/db/migrations/029_ai_disclosure.sql` (l'ultima esistente e' la 028).
- Testo disclosure fisso (dal design approvato): `Ciao! Sono l'assistente automatico di {nome}, un sistema di intelligenza artificiale. Scrivi OPERATORE se vuoi parlare con una persona.`
- Messaggio di attesa OPERATORE: `Ti passo una persona dello staff, un attimo!`
- Nome attivita' per la disclosure: `business_profile["nome"]` nel fast-path, `profilo.nome` nel ramo AI. Fallback `"Attivita"`.
- Nessuna firma continua nelle risposte successive; nessun pannello di configurazione tenant; nessun log di audit oltre la colonna timestamp.
- Convenzione del codebase: messaggi in italiano senza apostrofi tipografici (es. `piu'`, `attivita'`).

---

### Task 1: Migration 029 + `mark_ai_disclosure_sent`

**Files:**
- Create: `src/core/db/migrations/029_ai_disclosure.sql`
- Modify: `src/whatsapp/repository.py` (nuovo metodo dopo `get_contact_consent`, ~riga 320)
- Test: `tests/whatsapp/test_ai_disclosure.py` (nuovo)

**Interfaces:**
- Consumes: tabella `contacts` (schema.sql:21-31), pattern di `try_mark_replied` (repository.py:260-277).
- Produces: `Repository.mark_ai_disclosure_sent(contact_id: uuid.UUID) -> bool`. `True` solo per chi vince l'UPDATE concorrente; `False` se gia' valorizzato o contatto inesistente.

- [ ] **Step 1: Creare la migration**

`src/core/db/migrations/029_ai_disclosure.sql`:
```sql
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS ai_disclosure_sent_at TIMESTAMPTZ;
```

- [ ] **Step 2: Scrivere i test che falliscono**

`tests/whatsapp/test_ai_disclosure.py` (pattern copiato da `test_hitl_repository.py:9-80`, con schema minimale: schema.sql + 004 + 005 + 029):

```python
import uuid
import asyncpg
import pytest


pytestmark = pytest.mark.usefixtures("override_reset_db")


@pytest.fixture
async def disclosure_pool(postgres_container):
    dsn = postgres_container.get_connection_url().replace("+psycopg2", "")
    pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        with open("src/whatsapp/schema.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/004_gdpr.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/005_gdpr_consent.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/029_ai_disclosure.sql") as f:
            await conn.execute(f.read())
    yield pool
    await pool.close()


@pytest.fixture(autouse=True)
async def override_reset_db():
    pass  # questo file ha pool e reset propri


@pytest.fixture(autouse=True)
async def reset_disclosure_db(disclosure_pool):
    async with disclosure_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE contacts, conversations, messages, contact_consent_log CASCADE")


@pytest.fixture
async def repo(disclosure_pool):
    from src.whatsapp.repository import Repository
    return Repository(pool=disclosure_pool)


async def _make_contact(repo) -> dict:
    async with repo.pool.acquire() as conn:
        org = await conn.fetchrow(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Disclosure Test') RETURNING id",
            uuid.uuid4(),
        )
        contact = await conn.fetchrow(
            "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, $3) RETURNING id",
            uuid.uuid4(), org["id"], "+391234567891",
        )
    return dict(contact)


class TestMarkAiDisclosureSent:
    async def test_first_call_returns_true_and_sets_timestamp(self, repo):
        contact = await _make_contact(repo)
        result = await repo.mark_ai_disclosure_sent(contact["id"])
        assert result is True
        async with repo.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT ai_disclosure_sent_at FROM contacts WHERE id = $1", contact["id"])
        assert row["ai_disclosure_sent_at"] is not None

    async def test_second_call_returns_false(self, repo):
        contact = await _make_contact(repo)
        first = await repo.mark_ai_disclosure_sent(contact["id"])
        second = await repo.mark_ai_disclosure_sent(contact["id"])
        assert first is True
        assert second is False

    async def test_missing_contact_returns_false(self, repo):
        result = await repo.mark_ai_disclosure_sent(uuid.uuid4())
        assert result is False
```

- [ ] **Step 3: Verificare che i test falliscano**

Run: `python -m pytest tests/whatsapp/test_ai_disclosure.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'mark_ai_disclosure_sent'`

- [ ] **Step 4: Implementare il metodo nel repository**

In `src/whatsapp/repository.py`, dopo `get_contact_consent` (~riga 320):

```python
    async def mark_ai_disclosure_sent(self, contact_id: uuid.UUID) -> bool:
        """Atomicamente segna il contatto come destinatario della disclosure AI.
        Ritorna True solo per il chiamante che vince la race (primo UPDATE);
        False se la disclosure era gia' stata segnata o il contatto non esiste."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE contacts SET ai_disclosure_sent_at = NOW()
                   WHERE id = $1::uuid AND ai_disclosure_sent_at IS NULL
                   RETURNING id""",
                contact_id,
            )
            return row is not None
```

- [ ] **Step 5: Verificare che i test passino**

Run: `python -m pytest tests/whatsapp/test_ai_disclosure.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/db/migrations/029_ai_disclosure.sql src/whatsapp/repository.py tests/whatsapp/test_ai_disclosure.py
git commit -m "feat(gdpr): mark_ai_disclosure_sent atomico su contacts (migration 029)"
```

---

### Task 2: `check_human_request` nel WhatsAppService

**Files:**
- Modify: `src/whatsapp/service.py` (costa nte `HUMAN_REQUEST_KEYWORDS` ~riga 15; metodo nuovo dopo `check_opt_out`, ~riga 135)
- Test: `tests/whatsapp/test_service.py` (aggiungere test dopo `test_fast_path_no_match`, riga 135)

**Interfaces:**
- Consumes: `_normalize_text` (service.py:19-20).
- Produces: `WhatsAppService.check_human_request(text: str, lang: str = "it") -> bool`. `True` se il testo contiene una keyword di richiesta di una persona; `False` altrimenti.

- [ ] **Step 1: Scrivere i test che falliscono**

In `tests/whatsapp/test_service.py`, aggiungere:

```python
    async def test_check_human_request_keyword_it(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        assert await service.check_human_request("voglio parlare con un operatore") is True
        assert await service.check_human_request("parlare con una persona") is True

    async def test_check_human_request_keyword_en(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        assert await service.check_human_request("operator please", "en") is True

    async def test_check_human_request_normal_message(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        assert await service.check_human_request("quanto costano i menu") is False
```

- [ ] **Step 2: Verificare che falliscano**

Run: `python -m pytest tests/whatsapp/test_service.py::TestWhatsAppService::test_check_human_request_keyword_it -v`
Expected: FAIL — `AttributeError: 'WhatsAppService' object has no attribute 'check_human_request'`

- [ ] **Step 3: Implementare**

In `src/whatsapp/service.py`, dopo `OPT_OUT_KEYWORDS` (riga 13), aggiungere la costante:

```python
HUMAN_REQUEST_KEYWORDS = {
    "it": ["operatore", "umano", "parlare con una persona", "persona reale", "staff"],
    "en": ["operator", "human", "talk to a person", "real person"],
}
```

Dopo `check_opt_out` (fine ~riga 135), aggiungere il metodo:

```python
    async def check_human_request(self, text: str, lang: str = "it") -> bool:
        """True se il messaggio esplicita la richiesta di parlare con una persona."""
        normalized = _normalize_text(text)
        keywords = HUMAN_REQUEST_KEYWORDS.get(lang, HUMAN_REQUEST_KEYWORDS["it"])
        return any(kw in normalized for kw in keywords)
```

- [ ] **Step 4: Verificare che passino**

Run: `python -m pytest tests/whatsapp/test_service.py -v`
Expected: 3 nuovi test PASS, test esistenti PASS

- [ ] **Step 5: Commit**

```bash
git add src/whatsapp/service.py tests/whatsapp/test_service.py
git commit -m "feat(whatsapp): check_human_request per escape hatch OPERATORE"
```

---

### Task 3: Helper `decorate_with_disclosure` in inbound_processor

**Files:**
- Modify: `src/whatsapp/inbound_processor.py` (costanti ~riga 24; funzione modulo dopo `_profile_from_dict` ~riga 45)
- Test: `tests/whatsapp/test_inbound_processor.py` (nuovi test nella classe esistente)

**Interfaces:**
- Consumes: `Repository.get_or_create_contact(org_id, phone)` (repository.py:113), `Repository.mark_ai_disclosure_sent(contact_id)` (Task 1).
- Produces: `decorate_with_disclosure(org_id: str, from_number: str, testo: str, repo) -> str`. Ritorna testo con disclosure preposta se la disclosure non era stata inviata; altrimenti testo invariato. Il nome attivita' e' risolto dal chiamante (v. Task 4).

- [ ] **Step 1: Scrivere i test che falliscono**

In `tests/whatsapp/test_inbound_processor.py`, dopo la fixture `fake_tenant_config`, aggiungere un test unitario dell'helper:

```python
    async def test_decorate_with_disclosure_first_contact(
        self, app_config, mock_repo, mock_service
    ):
        from src.whatsapp.inbound_processor import decorate_with_disclosure, DISCLOSURE_TEXT
        mock_repo.get_or_create_contact = AsyncMock(return_value={"id": uuid.uuid4()})
        mock_repo.mark_ai_disclosure_sent = AsyncMock(return_value=True)
        out = await decorate_with_disclosure(
            str(uuid.uuid4()), "391234567890", "Siamo aperti.",
            mock_repo, nome_attivita="Trattoria Test",
        )
        assert out.startswith("Ciao! Sono l'assistente automatico di Trattoria Test")
        assert DISCLOSURE_TEXT.format(nome="Trattoria Test") in out
        assert out.endswith("Siamo aperti.")

    async def test_decorate_with_disclosure_second_contact(
        self, app_config, mock_repo, mock_service
    ):
        from src.whatsapp.inbound_processor import decorate_with_disclosure
        mock_repo.get_or_create_contact = AsyncMock(return_value={"id": uuid.uuid4()})
        mock_repo.mark_ai_disclosure_sent = AsyncMock(return_value=False)
        out = await decorate_with_disclosure(
            str(uuid.uuid4()), "391234567890", "Gia' vista.", mock_repo, nome_attivita="X"
        )
        assert out == "Gia' vista."
```

- [ ] **Step 2: Verificare che falliscano**

Run: `python -m pytest tests/whatsapp/test_inbound_processor.py -k "decorate_with_disclosure" -v`
Expected: FAIL — `ImportError: cannot import name 'decorate_with_disclosure'`

- [ ] **Step 3: Implementare**

In `src/whatsapp/inbound_processor.py`, dopo `ORG_SUSPENDED_REPLY` (riga 24), aggiungere:

```python
DISCLOSURE_TEXT = (
    "Ciao! Sono l'assistente automatico di {nome}, un sistema di intelligenza "
    "artificiale. Scrivi OPERATORE se vuoi parlare con una persona."
)

HUMAN_WAIT_REPLY = "Ti passo una persona dello staff, un attimo!"
```

Dopo `_profile_from_dict` (~riga 45), aggiungere la funzione:

```python
async def decorate_with_disclosure(org_id: str, from_number: str, testo: str, repo,
                                   nome_attivita: str = "Attivita") -> str:
    """Prepende la disclosure AI al primo messaggio automatico per quel contatto."""
    contact = await repo.get_or_create_contact(org_id, from_number)
    sent = await repo.mark_ai_disclosure_sent(contact["id"])
    if not sent:
        return testo
    return DISCLOSURE_TEXT.format(nome=nome_attivita) + "\n\n" + testo
```

- [ ] **Step 4: Verificare che passino**

Run: `python -m pytest tests/whatsapp/test_inbound_processor.py -k "decorate_with_disclosure" -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/whatsapp/inbound_processor.py tests/whatsapp/test_inbound_processor.py
git commit -m "feat(whatsapp): helper decorate_with_disclosure per AI Act"
```

---

### Task 4: Aggancio della disclosure nel pipeline (fast-path + risposta AI)

**Files:**
- Modify: `src/whatsapp/inbound_processor.py` (ramo `_process_one`: fast-path ~riga 113-117 e risposta AI ~riga 206-207)
- Test: `tests/whatsapp/test_inbound_processor.py` (test di primo contatto e contatto gia' visto)

**Interfaces:**
- Consumes: `decorate_with_disclosure(...)` (Task 3), `_send_ai_reply(...)` (inbound_processor.py:209), `tenant_config.business_profile`.
- Produces: nessuna interfaccia nuova; cambia il payload inviato nei due rami (disclosure in testa solo al primo contatto).

- [ ] **Step 1: Scrivere i test che falliscono**

In `tests/whatsapp/test_inbound_processor.py`, nella fixture `mock_repo` (riga 42-50) aggiungere:

```python
    repo.get_or_create_contact = AsyncMock(return_value={"id": uuid.uuid4()})
    repo.mark_ai_disclosure_sent = AsyncMock(return_value=True)
```

Nota: `mock_repo` usa `AsyncMock`, quindi `mark_ai_disclosure_sent` ritorna di default `True` (primo contatto). I test esistenti che verificano il payload esatto (`test_ai_reply_sent_when_no_escalation`, riga 103) si aspettano `payload["text"]["body"] == "Siamo aperti dalle 12 alle 15."` — con la disclosure questo cambia. Aggiornare quel test per verificare che il body **inizia** con la disclosure approvata:

```python
        payload_body = call_kwargs["payload"]["text"]["body"]
        assert payload_body.startswith("Ciao! Sono l'assistente automatico di Trattoria Test")
        assert payload_body.endswith("Siamo aperti dalle 12 alle 15.")
```

Aggiungere poi un test per il contatto gia' visto (disclosure non ripetuta) e un test per il fast-path decorato:

```python
    async def test_ai_reply_no_disclosure_on_second_contact(
        self, app_config, mock_repo, mock_service, fake_tenant_config, sample_msg
    ):
        mock_repo.mark_ai_disclosure_sent = AsyncMock(return_value=False)
        with patch("src.whatsapp.inbound_processor.load_tenant_config", AsyncMock(return_value=fake_tenant_config)), \
             patch("src.whatsapp.inbound_processor.genera_risposta_async", AsyncMock(return_value=RispostaOutput(
                 risposta="Siamo aperti.", richiede_umano=False, motivo="orari", categoria="info",
             ))):
            processor = InboundProcessor(app_config, mock_repo, mock_service)
            await processor.process_next_batch()

        call_kwargs = mock_service.send_whatsapp_message.call_args.kwargs
        assert call_kwargs["payload"]["text"]["body"] == "Siamo aperti."

    async def test_fast_path_reply_has_disclosure_on_first_contact(
        self, app_config, mock_repo, mock_service, fake_tenant_config, sample_msg
    ):
        mock_service.fast_path_match = AsyncMock(return_value="Ciao! Benvenuto.")
        with patch("src.whatsapp.inbound_processor.load_tenant_config", AsyncMock(return_value=fake_tenant_config)):
            processor = InboundProcessor(app_config, mock_repo, mock_service)
            await processor.process_next_batch()

        call_kwargs = mock_service.send_whatsapp_message.call_args.kwargs
        payload_body = call_kwargs["payload"]["text"]["body"]
        assert payload_body.startswith("Ciao! Sono l'assistente automatico di Trattoria Test")
        assert payload_body.endswith("Ciao! Benvenuto.")
```

- [ ] **Step 2: Verificare che falliscano**

Run: `python -m pytest tests/whatsapp/test_inbound_processor.py -v`
Expected: FAIL — `AssertionError` sul body (la disclosure non viene ancora preposta).

- [ ] **Step 3: Implementare**

In `_process_one`, nel ramo fast-path (riga 113-117), modificare per decorare prima di inviare:

```python
        fast_reply = await self.service.fast_path_match(text, business_profile_raw)
        if fast_reply:
            from_number = content.get("from", "")
            nome = (business_profile_raw or {}).get("nome") or "Attivita"
            decorated = await decorate_with_disclosure(org_id, from_number, fast_reply, self.repo, nome_attivita=nome)
            if await self.repo.try_mark_replied(msg["id"]):
                await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
            return
```

Nel ramo risposta AI (riga 206-207), decorare prima dell'invio:

```python
        from_number = content.get("from", "")
        decorated = await decorate_with_disclosure(org_id, from_number, risposta.risposta, self.repo, profilo.nome)
        if await self.repo.try_mark_replied(msg["id"]):
            await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
```

- [ ] **Step 4: Verificare che passino**

Run: `python -m pytest tests/whatsapp/test_inbound_processor.py -v`
Expected: tutti PASS, inclusi i 3 nuovi e i test esistenti aggiornati.

- [ ] **Step 5: Commit**

```bash
git add src/whatsapp/inbound_processor.py tests/whatsapp/test_inbound_processor.py
git commit -m "feat(whatsapp): disclosure AI al primo contatto su fast-path e risposta AI"
```

---

### Task 5: Escape hatch OPERATORE — escalation a un umano

**Files:**
- Modify: `src/whatsapp/inbound_processor.py` (ramo `_process_one`, dopo il blocco opt-out ~riga 89 e prima di `booking_service.handle_reminder_reply` ~riga 91)
- Modify: `src/whatsapp/service.py` (costante `HUMAN_REQUEST_KEYWORDS`, gia' aggiunta in Task 2)
- Test: `tests/whatsapp/test_inbound_processor.py`

**Interfaces:**
- Consumes: `WhatsAppService.check_human_request(text)` (Task 2), `HUMAN_WAIT_REPLY` (Task 3), `Repository.escalate_to_human` (repository.py:586), `enqueue_escalation` (inbound_processor.py:10).
- Produces: nessuna interfaccia nuova.

- [ ] **Step 1: Scrivere i test che falliscono**

In `tests/whatsapp/test_inbound_processor.py`, nella fixture `mock_service` (riga 54-59) aggiungere:

```python
    service.check_human_request = AsyncMock(return_value=False)
```

(preserva il comportamento esistente dei test). Aggiungere il test dell'escape hatch:

```python
    async def test_human_request_forces_escalation(
        self, app_config, mock_repo, mock_service, sample_msg
    ):
        mock_service.check_human_request = AsyncMock(return_value=True)
        mock_repo.escalate_to_human = AsyncMock(return_value={"id": sample_msg["conversation_id"], "ticket_status": "PENDING_STAFF"})
        with patch("src.whatsapp.inbound_processor.enqueue_escalation", MagicMock()) as mock_email:
            processor = InboundProcessor(app_config, mock_repo, mock_service)
            await processor.process_next_batch()

        mock_service.fast_path_match.assert_not_called()
        mock_repo.escalate_to_human.assert_awaited_once_with(str(sample_msg["conversation_id"]))
        mock_email.assert_called_once()
        # Nessuna disclosure sul messaggio di attesa (vedi spec §6)
        assert mock_service.send_whatsapp_message.await_count == 1
        body = mock_service.send_whatsapp_message.call_args.kwargs["payload"]["text"]["body"]
        assert "assistente automatico" not in body
        assert body == "Ti passo una persona dello staff, un attimo!"
        mock_repo.try_mark_replied.assert_awaited_with(sample_msg["id"])
```

- [ ] **Step 2: Verificare che falliscano**

Run: `python -m pytest tests/whatsapp/test_inbound_processor.py -k human_request -v`
Expected: FAIL — il ramo non esiste ancora.

- [ ] **Step 3: Implementare**

In `_process_one`, immediatamente dopo il blocco opt-out (riga 89) e prima di `if self.booking_service:` (riga 91), inserire:

```python
        wants_human = await self.service.check_human_request(text)
        if wants_human:
            from_number = content.get("from", "")
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            if await self.repo.try_mark_replied(msg["id"]):
                await self._send_ai_reply(org_id, msg, content, tenant_config, HUMAN_WAIT_REPLY)
            conv = await self.repo.escalate_to_human(str(msg["conversation_id"]))
            if conv:
                enqueue_escalation(
                    org_id=str(org_id),
                    conversation_id=str(msg["conversation_id"]),
                    contact_name=from_number or "cliente",
                    pool=self.repo.pool,
                )
            return
```

- [ ] **Step 4: Verificare che passino**

Run: `python -m pytest tests/whatsapp/test_inbound_processor.py -v`
Expected: tutti PASS, incluso il nuovo test.

- [ ] **Step 5: Commit**

```bash
git add src/whatsapp/inbound_processor.py tests/whatsapp/test_inbound_processor.py
git commit -m "feat(whatsapp): escape hatch OPERATORE forza escalation a umano"
```

---

### Task 6: Coerenza documentale (DPA, DPA HTML, roadmap)

**Files:**
- Modify: `docs/superpowers/dpa/DPA-whatsapp-ai-responder.md` (§10 e Allegato A)
- Modify: `src/core/gdpr/routes.py` (DPA_HTML, sezione 7 Data Subject Rights)
- Modify: `prompt-roadmap-saas-corretta.md` (riga 41 Punto 5 / nota AI Act)

**Interfaces:** nessuna (solo documentazione).

- [ ] **Step 1: Aggiornare il DPA markdown §10**

Sostituire in `docs/superpowers/dpa/DPA-whatsapp-ai-responder.md` l'attuale §10.1 (righe 205-213) con:

```markdown
10.1 Il Servizio genera risposte automatiche tramite un sistema di
intelligenza artificiale e, in conformità all'art. 50(1) del Regolamento
(UE) 2024/1689 ("AI Act"), informa gli utenti finali che stanno interagendo
con un sistema di IA al momento del primo contatto automatico: la prima
risposta generata dal sistema verso ciascun contatto inizia con la dicitura
"Sono l'assistente automatico di [attività], un sistema di intelligenza
artificiale" e offre la possibilità di richiedere di parlare con una persona
("OPERATORE"), che determina l'instradamento della conversazione a un
operatore umano del Titolare (HITL).

10.2 Resta a carico del Titolare ogni obbligo ulteriore previsto dall'AI Act
che non sia specificamente adempiuto dal Servizio (es. nei confronti di
utenti istituzionali o in relazione ad altri canali), da verificare con
l'assistenza di un legale.
```

- [ ] **Step 2: Aggiornare Allegato A del DPA**

In `docs/superpowers/dpa/DPA-whatsapp-ai-responder.md`, Allegato A (riga 266: riga "Consensi"), aggiungere dopo la riga "Consensi":

```markdown
| Trasparenza IA | timestamp del primo invio della disclosure (ai_disclosure_sent_at) | Adempimento obblighi di trasparenza AI Act art. 50(1) |
```

- [ ] **Step 3: Aggiornare il DPA HTML in gdpr/routes.py**

In `src/core/gdpr/routes.py`, DPA_HTML, sezione "7. Data Subject Rights" (righe 82-88), aggiungere una voce:

```html
  <li><strong>AI Transparency:</strong> the first automated reply to each new
      customer is preceded by a disclosure that the user is interacting with
      an AI assistant, with the option to be transferred to a human (HITL)</li>
```

- [ ] **Step 4: Aggiornare la roadmap**

In `prompt-roadmap-saas-corretta.md`, riga 41 (Punto 5), aggiornare la cella per riflettere l'adempimento AI Act disclosure. Esempio di testo:

```
GDPR/trasparenza AI — retention/export/delete/consenso + DPA bozza (docs/superpowers/dpa/) + disclosure AI Act art. 50 al primo contatto (migration 029, ai_disclosure_sent_at). Resta: validazione legale DPA e testo disclosure.
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/dpa/DPA-whatsapp-ai-responder.md src/core/gdpr/routes.py prompt-roadmap-saas-corretta.md
git commit -m "docs(gdpr): disclosure AI Act documentata in DPA, DPA HTML e roadmap"
```

---

## Self-Review (completata)

- **Spec coverage:** disclosure una tantum (Task 1, 3, 4) ✓; fast-path + risposta AI (Task 4) ✓; escape hatch OPERATORE con attesa + escalation HITL (Task 2, 5) ✓; esclusione org sospesa/opt-out/reminder (Task 5 lascia quei rami intatti) ✓; coerenza documentale DPA §10, Allegato A, DPA HTML, roadmap (Task 6) ✓.
- **Placeholder scan:** nessun TODO/TBD; ogni step ha codice concreto.
- **Type consistency:** `decorate_with_disclosure(org_id, from_number, testo, repo, nome_attivita)` usata nello stesso modo in Task 3 e Task 4; `mark_ai_disclosure_sent -> bool` coerente; `check_human_request(text, lang) -> bool` coerente.
- **Ordine pipeline:** opt-out → OPERATORE → reminder → sospesa → fast-path → AI (spec §6) rispettato nell'inserimento del Task 5 (dopo opt-out, prima di reminder).