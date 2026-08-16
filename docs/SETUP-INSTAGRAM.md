# Setup canale Instagram DM

Il canale Instagram (punto 10 della roadmap) riusa la stessa app Meta del
WhatsApp Cloud API: stesso `META_APP_SECRET`, stesso `META_VERIFY_TOKEN`,
stessa verifica firma `X-Hub-Signature-256`. Cambia solo l'envelope dei
webhook (`entry[].messaging[]` invece di `entry[].changes[].value`) e la
tabella delle credenziali per tenant (`instagram_accounts`, migration 030).

## Prerequisiti Meta

1. **Account Instagram Professional** (Business o Creator) collegato a una
   Facebook Page dell'attivita'.
2. Nell'app Meta (la stessa usata per WhatsApp):
   - aggiungere il prodotto **Instagram** (o Messenger for Instagram);
   - permesso `instagram_basic` (e `instagram_manage_messages` per i DM);
   - in *Webhooks* configurare l'URL `https://<host>/webhooks/instagram` con
     lo stesso verify token di `META_VERIFY_TOKEN`, sottoscrivendo il campo
     `messages`.
3. Un **Page Access Token** di lunga durata per la Page collegata.

## Configurazione del tenant

Salvare le credenziali del locale (il token viene cifrato Fernet a riposo
con `ENCRYPTION_KEY`):

```bash
curl -X POST https://<host>/api/instagram/account \
  -H "Authorization: Bearer <JWT>" \
  -H "X-Organization-Id: <org-uuid>" \
  -H "Content-Type: application/json" \
  -d '{"ig_user_id": "<IG professional account id>", "access_token": "<page token>"}'
```

- `ig_user_id` e' l'id dell'account IG del locale: e' il `recipient.id` che
  Meta invia nei webhook DM e la chiave di lookup tenant
  (`instagram_accounts.ig_user_id`, UNIQUE).
- Ruoli: scrittura owner/manager, lettura anche staff.
- Verifica: `GET /api/instagram/account` restituisce l'id (mai il token);
  `DELETE /api/instagram/account` scollega il canale.

## Come funziona

- **Ricezione**: `POST /webhooks/instagram` (`src/instagram/router.py`)
  verifica firma/size/replay, deduplica sul `mid` (prefisso `ig:`), risolve
  il tenant da `recipient.id`, crea contatto + conversazione con
  `canale='instagram'` e accoda il messaggio inbound (stessa coda `messages`
  del canale WhatsApp: `received_pending_ai`).
- **Pipeline**: `InboundProcessor` e' channel-agnostic: opt-out, escape hatch
  `OPERATORE`, disclosure AI Act, RAG, escalation HITL ed email valgono
  uguale. Il campo `canale` della conversazione (join in
  `claim_inbound_messages`) seleziona solo il canale di **invio** della
  risposta (`_send_ai_reply` dispatch).
- **Invio**: `InstagramService` → `POST graph.facebook.com/v20.0/{ig_user_id}/messages`
  con `{"recipient": {"id": <utente>}, "message": {"text": ...}}`.
- **Inbox HITL**: i ticket Instagram compaiono nell'inbox condivisa con
  badge canale; la reply manuale viene instradata su Instagram DM
  (`reply_to_ticket` dispatch su `conversations.canale`).
- **Usage**: `usage_events.metadata.channel = "instagram"` sul metering
  `ai_response`.

## Limiti noti (MVP)

- Solo messaggi di testo (niente media/sticker/reaction in ingresso: gli
  eventi senza `message.text` vengono ignorati).
- Un account Instagram per organizzazione.
- Stato di consegna (sent/delivered/read) non tracciato per IG: l'outbound
  passa a `sent` dopo l'ACK di Graph API.
- Nessun gate di quota specifico IG (il metering generale su
  `usage_events` resta attivo; il limite messaggi e' valutato dal canale
  WhatsApp).
