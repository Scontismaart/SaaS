-- 051_single_owner_per_org.sql
-- Vincolo di business e isolamento tenant: esattamente un solo owner per organizzazione (Invarianti 1, 2)

CREATE UNIQUE INDEX IF NOT EXISTS unique_owner_per_org
ON organization_memberships (organization_id)
WHERE ruolo = 'owner';
