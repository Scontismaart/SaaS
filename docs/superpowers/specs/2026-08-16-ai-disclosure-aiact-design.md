# AI Act Disclosure — Design

**Data:** 2026-08-16
**Stato:** bozza di design
**Obiettivo:** adeguare il prodotto all'art. 50(1) del Regolamento (UE) 2024/1689 (AI Act), che impone di informare le persone fisiche che interagiscono con un sistema di IA, salvo che risulti evidente dal contesto. Su WhatsApp di un'azienda non è evidente → serve disclosure.
**Approccio:** disclosure una tantum al primo contatto automatico di ciascun contatto; nessuna firma continua nelle risposte successive.

## 1. Ambito

La disclosure viene preposta alla **prima risposta automatica** generata dal sistema verso ciascun contatto, e mai più per quel contatto. Copre le risposte prodotte dal sistema che sostengono la conversazione:

1. **Risposta AI vera** (generata dal modello via CrewAI/OpenRouter).
2. **Fast-path** (saluti/orari, `src/whatsapp/service.py:137`).
3. **Escalation HITL** — nota: oggi `inbound_processor.py:194-204` esegue escalation senza inviare alcun messaggio al cliente; pertanto non esiste un messaggio outbound da decorare in questo ramo. Resta una nota per il futuro.

Sono **esclusi** i casi infrastrutturali che non fingono di essere IA e non sostengono la conversazione:

- Org sospesa (`ORG_SUSPENDED_REPLY`, `inbound_processor.py:24`).
- Risposta a reminder prenotazioni (`booking_service.handle_reminder_reply`).
- Messaggio di conferma opt-out (nessuna risposta).

## 2. Dati

Nuova migrazione `src/core/db/migrations/029_ai_disclosure.sql`:

```sql
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS ai_disclosure_sent_at TIMESTAMPTZ;
```

`NULL` = disclosure mai inviata; valorizzato = inviata (timestamp = prova di adempimento).
Nessuna nuova tabella, nessun campo aggiuntivo su `messages`.

## 3. Repository (`src/whatsapp/repository.py`)

Nuovo metodo **`mark_ai_disclosure_sent(contact_id) -> bool`**:

```sql
UPDATE contacts SET ai_disclosure_sent_at = NOW()
WHERE id = $1::uuid AND ai_disclosure_sent_at IS NULL
RETURNING id
```

- **Atomico e idempotente**: vince il primo UPDATE concorrente (pattern già usato in `try_mark_replied`, `repository.py:260`). Con due messaggi simultanei dallo stesso contatto, uno solo riceve `True` → una sola disclosure.
- Ritorna `True` se il `RETURNING` ha prodotto riga (ossia ha appena segnato la disclosure), `False` altrimenti.

## 4. Testo disclosure

```
Ciao! Sono l'assistente automatico di {nome}, un sistema di intelligenza
artificiale. Scrivi OPERATORE se vuoi parlare con una persona.

{risposta}
```

`{nome}` = nome dell'attività dal profilo (`profilo.nome`). Il testo è fisso (niente pannello di configurazione tenant in questo scope).

## 5. Decorazione della risposta (`src/whatsapp/inbound_processor.py`)

Helper **`decorate_with_disclosure(org_id, from_number, testo, repo) -> str`**:

1. `contact = await repo.get_or_create_contact(org_id, from_number)` (già usato nel ramo opt-out, `inbound_processor.py:79`).
2. `await repo.mark_ai_disclosure_sent(contact["id"])`.
3. se `True` → `DISCLOSURE_TEXT.format(nome).rstrip() + "\n\n" + testo`; se `False` → `testo` invariato.

Punti di aggancio (subito prima di `_send_ai_reply`):

- ramo fast-path: `inbound_processor.py:114-117`
- ramo risposta AI: `inbound_processor.py:206-207`

Il nome attività arriva dal `tenant_config.business_profile`. Con `from_number` ricavato da `content.get("from", "")` come già fatto in `_send_ai_reply`.

## 6. Escape hatch "OPERATORE"

La disclosure promette un'alternativa umana: va onorata. Nuovo check esplicito, modellato su `check_opt_out` (`service.py:129-135`), separato dal fast-path perché il risultato non è una risposta ma un'escalation.

**`src/whatsapp/service.py`** — nuovo metodo **`check_human_request(text, lang="it") -> bool`** con keyword:

```python
HUMAN_REQUEST_KEYWORDS = {
    "it": ["operatore", "umano", "parlare con una persona", "persona reale", "staff"],
    "en": ["operator", "human", "talk to a person", "real person"],
}
```

Uso `_normalize_text` (già in `service.py:19`), stessa meccanica di `check_opt_out`.

**`inbound_processor.py`** — nel ramo `_process_one`, inserito come primo blocco dopo il check opt-out (riga 89 in `inbound_processor.py`) e prima del blocco `booking_service.handle_reminder_reply` (riga 91):

- `if await self.service.check_human_request(text):` → escalation esplicita:
  1. inviare messaggio di attesa neutro al cliente: "Ti passo una persona dello staff, un attimo!" (invia via `_send_ai_reply`);
  2. `await self.repo.escalate_to_human(str(msg["conversation_id"]))` (già usato a `inbound_processor.py:195`);
  3. `enqueue_escalation(...)` come nel ramo di escalation esistente (`inbound_processor.py:197-202`);
  4. `await self.repo.try_mark_replied(msg["id"])`.
- Questo ramo **non** riceve la disclosure decorata (è una risposta di attesa che promette un umano, non un'output IA che finge).

Note:
- L'ordine del pipeline: opt-out (GDPR) → OPERATORE → reminder booking → org sospesa → fast-path → AI.
- Il messaggio di attesa è un comportamento nuovo ma minimale e giustificato: la disclosure lo promette; senza, il cliente che scrive OPERATORE non riceverebbe risposta (oggi l'escalation non risponde al cliente).

## 7. Test (TDD)

**`tests/whatsapp/test_service.py`:**
- `check_human_request` riconosce "voglio parlare con un operatore" (it).
- riconosce "operator please" (en).
- non riconosce testo normale ("quanto costano i menu").

**`tests/whatsapp/test_inbound_processor.py`:**
- primo contatto, risposta AI → payload con disclosure in apertura, `mark_ai_disclosure_sent` chiamato.
- primo contatto, fast-path → disclosure in apertura.
- contatto che ha già `ai_disclosure_sent_at` → nessuna disclosure (test con `mark_ai_disclosure_sent` che ritorna `False`).
- org sospesa → nessuna disclosure (payload = `ORG_SUSPENDED_REPLY` invariato).
- opt-out → nessuna risposta, nessuna disclosure.
- `check_human_request=True` → invio messaggio di attesa + `escalate_to_human` + `try_mark_replied`; nessuna disclosure.

**`tests/whatsapp/test_hitl_repository.py` o nuovo test repository**
- `mark_ai_disclosure_sent`: prima chiamata `True` (timestemp valorizzato); seconda `False`; concorrenza logica (idempotenza).

## 8. Coerenza documentale

- **DPA** `docs/superpowers/dpa/DPA-whatsapp-ai-responder.md` §10: aggiornare da "meramente informativo e non costituisce adempimento" a: il Servizio informa gli utenti finali al primo contatto automatico (testo di disclosure + possibilità di contattare una persona), ai sensi dell'art. 50(1) AI Act. Aggiornare l'Allegato A (riga "Contenuto comunicazioni" o nuova riga "Trasparenza IA") per includere la finalità di trasparenza.
- **DPA HTML** `src/core/gdpr/routes.py` (§7 diritti): aggiungere menzione della disclosure per coerenza col documento markdown.
- **Roadmap** `prompt-roadmap-saas-corretta.md`: aggiornare Punto 12 Guardrails o annotazione AI Act se presente.

## 9. Fuori scope

- Nessuna firma continua ("generato da IA") nelle risposte successive al primo contatto.
- Nessun pannello di configurazione tenant per il testo della disclosure.
- Nessun log di audit dedicato oltre alla colonna timestamp (sufficiente come prova di adempimento).
- Nessun tracciamento di esportazione/strutturazione della disclosure nei report.

## 10. Note legali

- Il presente adempimento tecnico implementa l'art. 50(1) AI Act per il canale WhatsApp, ma resta consigliata la validazione legale del testo e dell'allocazione degli obblighi tra Titolare (cliente B2B) e Responsabile (fornitore) nel §10 del DPA.
- La disclosure una tantum al primo contatto è coerente con la prassi regolatoria europea per i chatbot; la conversazione resta visibile nella coda WhatsApp del cliente.