# Phase 5 execution policy

- CRM AI tools are disabled in server source (`CRM_AI_TOOLS_ENABLED = False`).
  Environment, client settings and prompt instructions cannot enable them.
  Code remains available for a future caller/record/action authorization design.
  Responder agents and every fallback receive no executable tools.
- A blocked response loses its booking payload. Human escalation prevents booking.
  Live booking requires tenant and message identity, uses the trusted sender, and
  passes through BookingService validation and capacity checks. No TypeError retry.
- Booking responses use persisted state: confirmed, pending, or controlled failure.
  External sync failures require staff intervention, persisted for replay.
  Message-scoped replay resolves an existing booking before capacity checks.
- Inbound and authenticated simulator retain atomic quota reservations. Simulator
  additionally permits at most 20 requests per tenant per minute. Intent is
  heuristic-only in live AI paths; no separate unaccounted classifier call.
- Input is limited to 12,000 characters; responder history to 12 turns of 2,000
  characters each; retrieved context to 12,000 characters. Provider output is
  capped at 1,000 tokens; agent iterations at 3 and agent/provider retries at 1.
  Model attempts are capped at 3; asynchronous attempts share the provider deadline.
- Every attempted provider generation, including failures, reaches the existing
  tenant accounting batch. Unknown usage blocks subsequent AI and current booking.
  Successful attempts are not also counted as an aggregate response event.
  Shadow execution records usage even though it cannot mutate bookings.
- Provider errors expose coarse exception types only. Business profile validation
  does not log raw profile contents. No real provider is needed by regression tests.

No migration, production deployment, merge, or Phase 6 work is part of this change.
