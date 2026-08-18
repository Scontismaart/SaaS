"""Migration 033 (multilingua): colonne lingue sul profilo onboarding.

Default prudenti ["it"]/"it": il comportamento dei profili esistenti resta
identico. L'audit event_log (trigger) porta anche le lingue configurate.
"""

import json
import uuid

import pytest


pytestmark = pytest.mark.usefixtures("reset_db")


class TestMigration033Lingue:
    async def test_colonne_lingue_esistono(self, pg_pool):
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'onboarding_profiles' "
                "AND column_name = 'lingue_supportate'"
            )
            assert row is not None
            assert row["data_type"] == "jsonb"

            row = await conn.fetchrow(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'onboarding_profiles' "
                "AND column_name = 'lingua_default'"
            )
            assert row is not None
            assert row["data_type"] == "text"

    async def test_default_colonne(self, pg_pool):
        async with pg_pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Test') RETURNING id",
                uuid.uuid4(),
            )
            row = await conn.fetchrow(
                """INSERT INTO onboarding_profiles (organization_id, verticale, nome_attivita)
                   VALUES ($1, 'ristorante', 'X')
                   RETURNING lingue_supportate, lingua_default""",
                org["id"],
            )
            assert json.loads(row["lingue_supportate"]) == ["it"]
            assert row["lingua_default"] == "it"

    async def test_audit_event_log_porta_le_lingue(self, pg_pool):
        async with pg_pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Test') RETURNING id",
                uuid.uuid4(),
            )
            await conn.execute(
                """INSERT INTO onboarding_profiles
                   (organization_id, verticale, nome_attivita, lingue_supportate, lingua_default)
                   VALUES ($1, 'hotel_bnb', 'X', '["it","en"]'::jsonb, 'en')""",
                org["id"],
            )
            rows = await conn.fetch(
                "SELECT dettagli FROM event_log WHERE organization_id = $1 AND tipo_evento = 'onboarding'",
                org["id"],
            )
            assert len(rows) == 1
            dettagli = json.loads(rows[0]["dettagli"])
            assert dettagli["lingue_supportate"] == ["it", "en"]
            assert dettagli["lingua_default"] == "en"