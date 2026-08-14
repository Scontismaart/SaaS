# Smoke test — Onboarding (wizard org-scoped)

Verifica manuale rapida del flusso onboarding **task14**
(`onboarding_profiles` DB-backed, org-scoped, RLS, sync `business_profile`,
preview reale con LLM + RAG, upload documenti dal wizard).

## Prerequisiti

1. Backend avviato con DB raggiungibile (migration fino alla 028 applicata).
2. Un'API key (`.env` -> `API_KEY_SERVICE`) e l'UUID dell'organizzazione di
   test (`SELECT id FROM organizations LIMIT 1;`).

## Passi

1. **Config accesso**: aprire `web/index.html`, cliccare "Configura accesso"
   in alto a destra, inserire API key + Organization ID. Il wizard (vista
   Onboarding) parte dal template del verticale.

2. **Salvataggio profilo**: compilare attivita'/voce/servizi, completare il
   wizard fino ad "Avanti -> Completa". Verificare:
   - stato "Profilo salvato…", nome attivita' aggiornato in sidebar e chat;
   - in DB il profilo esiste per la sola org:
     ```sql
     SELECT organization_id, verticale, nome_attivita
     FROM onboarding_profiles;
     ```
   - `organizations.business_profile` sincronizzato (1 riga per riga sopra):
     ```sql
     SELECT id, business_profile->>'nome' FROM organizations;
     ```
   - un evento di audit scritto dal trigger `log_onboarding_event`:
     ```sql
     SELECT organization_id, tipo_evento, source_table, testo_originale
     FROM event_log WHERE tipo_evento = 'onboarding';
     ```

3. **Isolamento multi-tenant**: con una seconda org (stessa API key, altro
   `X-Organization-Id` / altra credenziale) la GET `/api/onboarding/profilo`
   deve rispondere `{"profilo": null}` e il salvataggio NON deve toccare la
   riga della prima org.

4. **Preview reale**: nella vista Onboarding, "Genera preview" deve girare
   il vero responder (crew + LLM). Prima volta senza documenti: parte con
   contesto vuoto senza errori.

5. **Upload documenti (step 05)**: caricare un PDF/txt dal wizard; verificare
   `Indicizzati N chunk`, poi chiedere altro nel pannello Documenti o
   generare una preview dopo aver caricato un documento che contiene la
   risposta: la risposta deve usare il contenuto del documento.

6. **Chat demo invariat**: `/api/messaggio` continua a usare i profili demo
   statici (`PROFILI_DEMO`), il profilo onboarding non la tocca.

## Cosa NON deve succedere

- 401/403 sulla vista Onboarding con credenziali valide;
- profilo di un'org visibile/modificabile da un'altra org;
- preview in errore per mancanza di documenti (contesto vuoto = ok);
- `data/onboarding_profiles.json` responsabile di qualcosa (rimosso dal flusso).