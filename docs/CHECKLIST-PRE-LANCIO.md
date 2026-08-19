# Checklist pre-lancio — Melpis

File vivo: aggiungiamo qui ogni cosa da testare/verificare prima di poter
lanciare il progetto in produzione. Non cancellare le voci fatte, spuntarle
(`[x]`) cosi' resta traccia di cosa e' stato verificato e quando.

---

## Google Calendar Sync

- [ ] **Google Cloud Console**: creare OAuth 2.0 Web Client, abilitare Calendar API
- [ ] **Ruotare `data/client_secret.json`** (se la credenziale è ancora viva dalla fase di sviluppo)
- [ ] **Configurare `.env`**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
- [ ] **Eseguire migration DB**: 019 (`google_calendar_credentials`), 020 (`bookings.google_event_id`), 021 (`oauth_nonces`)
- [ ] **Test OAuth flow**: connettere un calendario di test via `GET /api/calendar/auth`, verificare callback, controllare `GET /api/calendar/status` -> `"connected": true`
- [ ] **Test sync creazione**: creare una prenotazione via `POST /api/bookings`, verificare che l'evento appaia su Google Calendar
- [ ] **Test sync cancellazione**: cancellare la prenotazione, verificare che l'evento sparisca dal calendario
- [ ] **Test revoca token**: disconnettere il calendario da Google Account, verificare che `sync_enabled` passi a `false` e l'errore venga loggato

## WhatsApp / Meta Cloud API

- [ ] **Test end-to-end reale**: numero WhatsApp Business verificato su Meta,
      `META_APP_SECRET`/`META_VERIFY_TOKEN` reali in produzione, un messaggio
      vero mandato da un telefono reale deve attraversare tutto il flusso:
      webhook riceve -> AI genera risposta -> risposta arriva su WhatsApp
      (o, se richiede_umano, il ticket appare in inbox e l'email di
      escalation arriva al titolare). Mai testato finora, solo mockato.

## Onboarding / dashboard (auth transitoria)

- [ ] **Sostituire l'auth transitoria del pannello** (`X-API-Key` +
      `X-Organization-Id` salvati nel localStorage del browser) con la
      sessione Supabase JWT reale: oggi il frontend tiene la credenziale in
      chiaro nel browser, e `get_organization_context` (dependencies.py) la
      scambia per un membro dell'org solo se `source != "api_key"`. Finché
      resta così, esporre il backend SOLO su HTTPS e non condividere l'API
      key del pannello con celle esterne.
- [ ] **Badge stato WhatsApp Business** nel wizard (step 04): oggi lo step
      registra solo il flag `whatsapp_collegato` senza interrogare Meta
      Cloud API; il collegamento reale arriverà con l'Embedded Signup
      self-service (v. design 2026-07-24-whatsapp-integration-design, Punto 7).
- [ ] **Verifica `event_log` di onboarding**: dopo il salvataggio del profilo
      deve comparire un record `tipo_evento='onboarding'` (scritto dal trigger
      `log_onboarding_event`, migration 028).
