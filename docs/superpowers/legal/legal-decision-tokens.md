# Decision tokens for legal review

These tokens are intentionally unresolved until legal counsel and the service
owner approve them. They are not public identity values and must never be
invented by a deployment operator.

| Token | Required release value | Owner |
| --- | --- | --- |
| `{{LEGAL_TERMS_REVIEW_APPROVAL}}` | `LEGAL_TERMS_REVIEW_APPROVED=true` | Legal counsel |
| `{{LEGAL_PRIVACY_REVIEW_APPROVAL}}` | `LEGAL_PRIVACY_REVIEW_APPROVED=true` | Privacy/legal counsel |
| `{{LEGAL_DPA_REVIEW_APPROVAL}}` | `LEGAL_DPA_REVIEW_APPROVED=true` | Privacy/legal counsel |
| `{{LEGAL_PUBLIC_DOCUMENTS_REVIEW}}` | `LEGAL_PUBLIC_DOCUMENTS_REVIEWED=true` | Legal counsel + release owner |
| `{{LEGAL_PAYMENT_SUSPENSION_DAYS}}` | positive integer | Commercial/legal owner |
| `{{LEGAL_ACCOUNT_TERMINATION_DAYS}}` | positive integer | Commercial/legal owner |

`scripts/release_preflight.py` rejects a commercial release unless every
approval flag is exactly `true` and both day values are explicit positive
integers. The rendered public legal pages use only the separate reviewed
identity fields listed in `legal-identity-tokens.md`.
