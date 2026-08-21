# ADR 002: Why service_role is used

## Context
Our Python backend needs to manage data across all tenants seamlessly and perform background maintenance.

## Decision
We use the Supabase `service_role` key to bypass RLS in the backend. 
Therefore, **application-level tenant isolation is mandatory**. RLS remains enabled strictly as a defense-in-depth measure against direct DB attacks, misconfigurations, or future client-side authenticated queries.
