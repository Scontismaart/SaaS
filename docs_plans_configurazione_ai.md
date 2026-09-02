# Configurazione AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Creare una nuova sezione di primo livello "Configurazione AI" nella dashboard (sotto il gruppo Assistente della sidebar) che unifica Identità dell'attività, Tono/Personalità, Multilingua e Regole di Escalation a Umano; rimuovere "Profilo attività" e "Assistente & Regole" dalla sotto-sidebar di Impostazioni; eliminare i campi duplicati (textarea servizi non strutturati) e garantire la sincronizzazione bidirezionale degli orari di apertura con la Knowledge Base RAG a Priorità 1.

**Architecture:** 
- Frontend: Aggiunta del nav-item `configurazione-ai` nella sidebar principale (gruppo Assistente); creazione del pannello `<section data-view-panel="configurazione-ai">` in `web/index.html` con 4 card logiche (Identità & Settore, Stile comunicativo, Multilingua, Regole di escalation); rimozione dei pulsanti e pannelli obsoleti da `web/index.html` e pulizia filtri ricerca impostazioni; unificazione della logica in `web/app.js`.
- Backend: Sincronizzazione API per `/api/onboarding/profilo`: quando gli orari di apertura vengono aggiornati da "Configurazione AI", sincronizzare automaticamente sia `organizations.business_profile` sia l'indicizzazione RAG (Priorità 1) di Dati Struttura, in modo che l'AI risponda coerentemente ovunque vengano modificati. Rimozione della dipendenza dalla vecchia textarea non strutturata dei servizi.
- Test: Test unitari e di integrazione per garantire che il salvataggio del profilo aggiorni RAG, non ci siano regressioni nei verticali o nelle escalation, e che la navigazione dashboard risponda correttamente.

**Tech Stack:** Python 3.12 (FastAPI, asyncpg, Pydantic), Vanilla HTML5/CSS3/ES6, PostgreSQL 16 con pgvector, Pytest.

**Spec:** Approvazione utente del 2026-09-02:
- Nome sezione sidebar: "Configurazione AI" (sotto il gruppo Assistente).
- Rimosse le schede "Profilo attività" e "Assistente & Regole" da Impostazioni.
- Gli orari di apertura si possono inserire sia in "Configurazione AI" (Identità) sia in "Conoscenza > Dati struttura", con sincronizzazione reciproca.
- Eliminata la textarea servizi duplicata e non tipizzata in favore del listino tipizzato di Conoscenza.

## Global Constraints
- Tenant Isolation Invariant: ogni query DB deve essere vincolata a `organization_id`.
- Sincronizzazione atomica tra `onboarding_profiles`, `organizations.business_profile` e chunk RAG di Priorità 1.
- Nessuna regressione sui 5 verticali (`parrucchiere`, `ristorante`, `centro_estetico`, `hotel_bnb`, `studio_medico_dentista`).
- Design consistente con la UI esistente (CSS dashboard, dash-card, wizard-label, switch, responsive design mobile).

---

### Task 1: Backend Sync - Unificazione e Sincronizzazione Orari & Profilo

**Files:**
- Modify: `src/core/onboarding.py:140-170`
- Modify: `src/api/main.py:710-730`
- Test: `tests/core/test_onboarding_sync.py`

**Interfaces:**
- Consumes: `OnboardingProfileInput` (`src/models/schemas.py`), `repo.save_onboarding_profile`, `repo.update_org_business_profile`
- Produces: API endpoint `POST /api/onboarding/profilo` aggiorna `onboarding_profiles`, `organizations.business_profile`, e re-indicizza automaticamente il chunk RAG `dati_struttura` (Priorità 1) per gli orari se modificati.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_onboarding_sync.py
import pytest
from unittest.mock import patch

@pytest.mark.asyncio
async def test_save_profile_syncs_rag_struttura(async_client, repo, sample_org):
    """Verifica che salvando il profilo con nuovi orari, il chunk RAG a Priorità 1 venga aggiornato."""
    headers = {"X-API-Key": "test-api-key-12345", "X-Organization-Id": str(sample_org["id"])}
    
    payload = {
        "verticale": "parrucchiere",
        "nome_attivita": "Salone Top",
        "orari": "Lun-Ven 09:00-19:00",
        "descrizione": "Salone unisex moderno",
        "tono": "professionale_caloroso",
        "servizi": [],
        "regole_escalation": ["Clienti arrabbiati"],
        "lingue_supportate": ["it"],
        "lingua_default": "it"
    }
    
    with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
        resp = await async_client.post("/api/onboarding/profilo", json=payload, headers=headers)
    assert resp.status_code == 200
    
    # Verifica che nei chunk attivi ci siano i nuovi orari con Priorità 1 (dati_struttura)
    chunks = await repo.list_all_active_chunks(sample_org["id"])
    orari_chunks = [c for c in chunks if "Lun-Ven 09:00-19:00" in c["content"]]
    assert len(orari_chunks) >= 1
    assert orari_chunks[0]["tipo"] == "dati_struttura"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_onboarding_sync.py -v`
Expected: FAIL (il salvataggio attuale di onboarding non crea/aggiorna il chunk RAG `dati_struttura` per gli orari)

- [ ] **Step 3: Implement minimal backend synchronization in `src/api/main.py` e `src/core/onboarding.py`**

In `src/api/main.py`: nel controller `onboarding_salva_profilo`, quando viene salvato il profilo, re-indicizzare il documento `dati_struttura` includendo sia i `servizi_strutturati` correnti sia i nuovi `orari`, garantendo che l'AI trovi sempre gli orari corretti a Priorità 1.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_onboarding_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/core/test_onboarding_sync.py src/core/onboarding.py src/api/main.py
git commit -m "feat(backend): sync business profile hours with RAG priority 1 chunks"
```

---

### Task 2: Markup HTML - Nuova Vista "Configurazione AI" e Rimozione Schede da Impostazioni

**Files:**
- Modify: `web/index.html:58-71` (aggiunta sidebar nav item)
- Modify: `web/index.html:1370-1400` (rimozione pulsanti profilo e assistente da impostazioni)
- Modify: `web/index.html:1495-1635` (rimozione pannelli vecchi da impostazioni e creazione sezione `configurazione-ai`)
- Modify: `web/style.css:4500-4650` (stili per la vista Configurazione AI)

**Interfaces:**
- Consumes: Elementi DOM `<button data-view="configurazione-ai">`, `<section data-view-panel="configurazione-ai">`
- Produces: Nuova vista dedicata con form identità, tono, multilingua e regole escalation. Nessun campo duplicato per servizi non strutturati.

- [ ] **Step 1: Modificare la sidebar in `web/index.html`**

Aggiungere sotto il gruppo "Assistente":
```html
      <span class="nav-group-label" aria-hidden="true">Assistente</span>
      <button class="nav-item" type="button" data-view="assistente">
        <span class="nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none"><path d="M4 5.5h16v10H9l-4 4v-4H4v-10Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
        </span>
        Simulatore AI
      </button>
      <button class="nav-item" type="button" data-view="conoscenza">
        <span class="nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15.5H6.5A2.5 2.5 0 0 0 4 21V5.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20M8.5 7.5h7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </span>
        Conoscenza <span class="nav-badge" data-notification-badge="conoscenza" hidden></span>
      </button>
      <button class="nav-item" type="button" data-view="configurazione-ai">
        <span class="nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none"><rect x="3" y="6" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.8"/><circle cx="8.5" cy="12" r="1.5" fill="currentColor"/><circle cx="15.5" cy="12" r="1.5" fill="currentColor"/><path d="M12 2v4M9 16h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </span>
        Configurazione AI
      </button>
```

- [ ] **Step 2: Rimuovere "Profilo attività" e "Assistente & Regole" dalla sotto-sidebar di Impostazioni**

In `web/index.html`:
- Rimuovere `<button data-settings-cat-btn="profilo">` e `<button data-settings-cat-btn="assistente-regole">`.
- Rimuovere i relativi pannelli `data-settings-panel="profilo"` e `data-settings-panel="assistente-regole"` dall'interno di `<main class="settings-content-area">`.
- Aggiornare `Generale` in Impostazioni affinché contenga unicamente le impostazioni generali di sistema (Fuso orario e localizzazione).

- [ ] **Step 3: Creare la sezione completa `<section class="view view-hidden" data-view-panel="configurazione-ai">`**

Inserire la nuova vista strutturata in 4 card chiare:
1. **Identità dell'attività**: Nome dell'attività, Settore/Verticale (select con i 5 verticali), Descrizione breve dell'attività, Orari di apertura (con nota esplicita di sincronizzazione automatica con la Knowledge Base).
2. **Personalità e Tono di voce**: Preset stile comunicativo + textarea istruzioni tono specifiche.
3. **Multilingua**: Griglia selezione lingue abilitate (IT, EN, ES, FR, DE) + select lingua predefinita.
4. **Regole di Prudenza ed Escalation a Umano**: Lista interattiva delle regole con checkbox e pulsante di eliminazione + input per aggiungere nuove regole personalizzate.
5. Barra azioni: Pulsante "Salva configurazione AI" con feedback visivo di stato.

- [ ] **Step 4: Aggiornare `web/style.css`**

Aggiungere stili specifici per `.ai-config-grid`, le card di raggruppamento e gli elementi di stato, mantenendo piena coerenza estetica.

- [ ] **Step 5: Verificare la struttura HTML**

Controllare che non ci siano ID duplicati o tag non chiusi.

---

### Task 3: Client Script - Logica Frontend in `web/app.js`

**Files:**
- Modify: `web/app.js:770-800` (routing della vista `configurazione-ai`)
- Modify: `web/app.js:5915-6130` (migrazione e isolamento del modulo da impostazioni alla nuova vista)
- Modify: `web/app.js:3450-3500` (sincronizzazione orari tra Conoscenza e Configurazione AI)

**Interfaces:**
- Consumes: API `GET /api/onboarding/profilo` e `POST /api/onboarding/profilo`
- Produces: Funzione `caricaConfigurazioneAI()` e `salvaConfigurazioneAI()` attivata al cambio vista su `configurazione-ai` e al click del form.

- [ ] **Step 1: Aggiornare il router di navigazione viste in `web/app.js`**

Nel listener della sidebar (`sidebar-nav`):
```javascript
if (viewName === "configurazione-ai") {
  caricaConfigurazioneAI();
}
```

- [ ] **Step 2: Ristrutturare il modulo JS in `web/app.js`**

Rinominare ed estendere `inizializzaProfiloImpostazioni` in `inizializzaConfigurazioneAI`:
- Collegare i campi della nuova vista `configurazione-ai` (`ai-cfg-nome`, `ai-cfg-verticale`, `ai-cfg-descrizione`, `ai-cfg-orari`, `ai-cfg-tono-select`, `ai-cfg-tono-custom`, `ai-cfg-lingua-default`, ecc.).
- Rimuovere la gestione della vecchia textarea servizi grezza (`settings-profile-servizi`).
- Al salvataggio con successo, se la vista Conoscenza è aperta o viene successivamente visitata, aggiornare anche il campo orari di `kb-struttura-orari`.
- Viceversa: quando l'utente salva in "Conoscenza > Dati struttura", aggiornare anche il campo orari in `ai-cfg-orari`.

- [ ] **Step 3: Aggiornare il motore di ricerca interno alle Impostazioni**

In `web/app.js`: aggiornare la lista delle categorie cercabili in Impostazioni rimuovendo `profilo` e `assistente-regole`, evitando errori di riferimento a pulsanti non più presenti.

---

### Task 4: Verifica Automatica e Regression Test

**Files:**
- Create: `tests/core/test_configurazione_ai_e2e.py`
- Run: `pytest tests/core/`

**Interfaces:**
- Consumes: Test suite backend e API
- Produces: 100% test verdi su navigazione, salvataggio profilo, isolamento tenant, sincronizzazione orari e vertical strategy.

- [ ] **Step 1: Scrivere test E2E `test_configurazione_ai_e2e.py`**

Testare:
1. Salvataggio configurazione AI (Nome, Verticale, Descrizione, Orari, Tono, Multilingua, Regole escalation).
2. L'AI risponde usando le nuove impostazioni salvate da "Configurazione AI".
3. Gli orari modificati da "Configurazione AI" sono visibili e utilizzati dal RAG sia nel responder sia in "Dati struttura".
4. Nessun leak multi-tenant tra due organizzazioni distinte.

- [ ] **Step 2: Eseguire la suite di test completa**

Run: `python -m pytest tests/core/test_configurazione_ai_e2e.py tests/core/test_conoscenza_e2e.py tests/core/test_conoscenza_completa.py tests/core/test_onboarding_sync.py`
Expected: 100% PASS

- [ ] **Step 3: Eseguire `graphify update .`**

Mantenere allineato il grafo di sistema.

---
