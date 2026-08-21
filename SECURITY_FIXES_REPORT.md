# Security Hardening - Round 2 Fixes Report

Questo file descrive nel dettaglio le modifiche apportate per risolvere le due criticità emerse dalla revisione redteam indipendente. Può essere usato come changelog per la revisione da parte di Claude o altri revisori.

## FIX 1: IP Spoofing via `X-Forwarded-For` (Severità ALTA - BLOCCANTE)
**Problema:** L'estrazione dell'IP client per le verifiche di rete interna/sicura in `api_key_guard.py` e `docs.py` utilizzava il primo elemento della catena `X-Forwarded-For`. Poiché l'applicativo gira dietro un proxy (Traefik), il primo elemento è quello fornito dal client stesso, permettendo un banale bypass tramite IP Spoofing (inviando `X-Forwarded-For: 127.0.0.1`).

**Correzione apportata:**
1. **Creazione Modulo Comune (`src/core/auth/trusted_network.py`)**:
   - Creata una funzione centralizzata `get_client_ip` che elabora l'header `X-Forwarded-For` estraendo l'**ultimo** indirizzo IP della catena (quello accodato in modo sicuro da Traefik al momento della ricezione della TCP connection).
   - Aggiunta la funzione `is_ip_in_allowed_cidrs` per gestire unificatamente il check su reti autorizzate, garantendo l'assenza di duplicazioni di logica core e rimuovendo i parsing stringa manuali sparsi.
2. **Refactoring di `api_key_guard.py` e `docs.py`**:
   - I file sono stati aggiornati per importare e utilizzare esclusivamente `get_client_ip` e `is_ip_in_allowed_cidrs` da `trusted_network.py`.
3. **Nuovi Test Unitari (`tests/core/auth/test_trusted_network.py`)**:
   - Aggiunto un test specifico che simula una richiesta forgiata da un attaccante con `X-Forwarded-For: 127.0.0.1, 203.0.113.1` (dove Traefik ha accodato l'IP reale 203.0.113.1 al fondo della lista spoofata). Il test dimostra inequivocabilmente che la richiesta viene correttamente identificata come proveniente da `203.0.113.1` (IP non fidato) e quindi bloccata/respinta, impedendo il bypass.

## FIX 2: Verifica Decorativa del Backup Drill (Severità MEDIA/ALTA)
**Problema:** Lo script `drill.py`, dopo aver eseguito dump e restore su un DB di verifica, confermava l'integrità del processo tramite un semplice `SELECT 1;`. Questo verificava esclusivamente la responsività del server Postgres, autorizzando backup vuoti, troncati o corrotti a patto che il processo pg_restore non lanciasse eccezioni terminali. Di conseguenza, il test mockava banalmente l'invocazione di `subprocess.run` e non verificava i dati.

**Correzione apportata:**
1. **Verifica Sostanziale dell'Integrità Dati (`src/core/backup/drill.py`)**:
   - Abbandonato `subprocess` via `psql` per i conteggi in favore di connessioni dirette con `asyncpg` (il driver core del progetto).
   - Lo script ora registra il numero di righe nella tabella `organizations` del database sorgente **prima** di effettuare il dump.
   - Dopo il ripristino, lo script esegue vere query di `COUNT(*)` su `organizations` e `user_profiles` del database di verifica.
   - Viene lanciata un'eccezione critica (che triggera gli alert Sentry preesistenti) se:
     - Le organizzazioni post-restore sono inferiori a quelle pre-dump (sintomo di un restore troncato/parziale).
     - Le organizzazioni o profili utente risultano pari a zero ma il database sorgente conteneva dati prima del dump.
2. **Simulazione e Fallimento nel Test (`tests/core/test_backup_drill.py`)**:
   - Passaggio a test asincroni via `pytest.mark.asyncio`.
   - Adattato il test per impiegare il reale database `testcontainers` gestito in `conftest.py` con le fixture `pg_pool` e `sample_org` (popolato a 1 org).
   - Implementato un nuovo test (`test_backup_restore_drill_detects_empty_restore`) che, pur mockando i tool a riga di comando Postgres non presenti nell'host di CI, simula un ripristino non riuscito **troncando deliberatamente la tabella `organizations`** nel DB di test. Il test certifica che il sistema di alert rileva il troncamento (COUNT 0 contro un pre-dump di 1) e genera la corretta `RuntimeError("Integrità compromessa")` bloccando il test.

## STATO FINALE (Punto 10)
- Eseguito con successo un `graphify update .` che ha aggiornato i nodi dell'AST per permettere ai sistemi RAG di visualizzare le difese aggiornate (es. la nuova dipendenza da `trusted_network.py`).
- Il codice è stato committato e pushato con successo, pronto per la review.
