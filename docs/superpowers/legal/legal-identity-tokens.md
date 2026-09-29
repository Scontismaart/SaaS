# Legal identity tokens (go-live blocker)

Do not publish a customer-facing legal document until every token below is
replaced with verified information and the legal review is approved. These are
deliberately not guessed from the product name or domain.

| Token | Production environment key | Required use |
|---|---|---|
| `{{LEGAL_ENTITY_NAME}}` | `LEGAL_ENTITY_NAME` | provider/controller legal name |
| `{{LEGAL_ENTITY_REGISTERED_OFFICE}}` | `LEGAL_ENTITY_REGISTERED_OFFICE` | registered office |
| `{{LEGAL_ENTITY_VAT_NUMBER}}` | `LEGAL_ENTITY_VAT_NUMBER` | VAT/tax identifier |
| `{{LEGAL_PRIVACY_CONTACT_EMAIL}}` | `LEGAL_PRIVACY_CONTACT_EMAIL` | privacy/DPA contact |
| `{{LEGAL_FORUM}}` | `LEGAL_FORUM` | agreed competent court, where applicable |
| `{{LEGAL_DOCUMENT_EFFECTIVE_DATE}}` | `LEGAL_DOCUMENT_EFFECTIVE_DATE` | verified legal-document effective date |

`scripts/release_preflight.py` rejects a production configuration when any of
these values is absent or still a placeholder. Rendering/replacing the public
documents remains a reviewed release step; the source tokens must never be
silently replaced with invented legal facts.
