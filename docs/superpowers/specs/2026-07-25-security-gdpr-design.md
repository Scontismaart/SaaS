# Security & GDPR Compliance Design

## Audit Findings (Phase 1)
See `prompt-roadmap-saas.md` P0-5 for full audit. Key findings:
- `data/client_secret.json`, `data/gmail_tokens/*.token`, `data/gmail_oauth_session.json`, `data/email_config.json` — tracked in git, NOT in .gitignore
- ENCRYPTION_KEY used for decrypt in `config.py` but NO encrypt-on-save exists
- Gmail token pickle stored in clear `data/gmail_tokens/*.token`
- No PII redaction in logging
- No data retention/export/delete API

## Architecture — 6 Modules

### Module 1: Secrets & .gitignore
- `git rm --cached` for: `data/client_secret.json`, `data/gmail_tokens/`, `data/gmail_oauth_session.json`, `data/email_config.json`
- New `.gitignore` additions: `data/*.json`, `data/gmail_tokens/`, `*.token`, `credentials.json`, `service-account*.json`, `.env.local`, `.env.production`
- `email_config.json` content migrated to env vars. Config file removed from filesystem.

### Module 2: Token Encryption (Art. 32)
- WhatsApp `access_token`: Fernet encrypt BEFORE DB write (in repo or service layer)
- Gmail tokens: replace `pickle.dump()` with `Fernet.encrypt()` in `gmail_token_store.py`
- Single `ENCRYPTION_KEY` for both
- `.env.example` includes: `# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- Remove empty string fallback — fail hard if ENCRYPTION_KEY unset

### Module 3: PII Redaction in Logs
- Custom logging filter that intercepts LogRecord
- Regex patterns for: email, phone numbers, message body content
- Replaces matches with `[REDACTED]`
- Applied at root logger level

### Module 4: Data Retention & Soft-delete (Art. 5)
- Column `deleted_at TIMESTAMPTZ` on: `messages`, `conversations`, `contacts`
- All repository read queries filter `WHERE deleted_at IS NULL`
- Column `message_retention_days INTEGER DEFAULT 90` on `organizations`
- Background job: messages with `created_at + retention_days < now()` → set `deleted_at = now()`
- Cleanup job: records with `deleted_at + 30gg < now()` → physical DELETE
- Referential integrity: conversations with ALL messages deleted → soft-delete cascade

### Module 5: GDPR Data Rights API (Art. 17 & 20)
- `GET /api/gdpr/export` — owner-only. JSON export of all tenant data (messages, contacts, conversations, bookings, reviews, documents). Returns download link or streaming response.
- `POST /api/gdpr/delete` — owner-only. Hard-delete entire organization with ON DELETE CASCADE. Irreversible. Audit logged. Returns confirmation.
- Both rate-limited and audit-logged.

### Module 6: DPA Template
- Written to `docs/superpowers/dpa/` as markdown
- Sections: scope, data processed, sub-processors, data retention, security measures, DPO contact

## Key Constraints
- CORS: already dynamic from `CORS_ORIGINS` env var. No wildcard. Verify in production.
- Retention: soft-delete invisible at app level (filtered in repository layer). Hard-delete only via GDPR Art 17 endpoint.
- Encryption: single key for all token types. Key rotation not in v1 scope.
