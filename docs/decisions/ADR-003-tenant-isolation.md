# ADR 003: Tenant isolation strategy

## Context
We are a multi-tenant SaaS application managing sensitive conversational and booking data.

## Decision
Every tenant-scoped table MUST have an `organization_id` (or a direct/provably derivable relationship). The backend code MUST filter by this ID in every query. RLS is enabled as a secondary safety net.
