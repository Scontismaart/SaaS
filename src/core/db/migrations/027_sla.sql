-- Migration 027: SLA per HITL
-- Tempo massimo (minuti) entro cui lo staff deve rispondere a un ticket
-- escalato (PENDING_STAFF). Calcolato a runtime come pending_staff_at + sla_minutes.

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS sla_minutes INTEGER NOT NULL DEFAULT 15
    CHECK (sla_minutes > 0 AND sla_minutes <= 1440);