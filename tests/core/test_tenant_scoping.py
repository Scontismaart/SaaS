"""Regressione tenant-isolation (task 4, brief 2026-08-22-tenant-scoping-wrapper-ci).

Una criticita' = un test dedicato (matrice di tracciabilita' nel brief).
Seed: due organizzazioni su pg_pool full-schema (tests/core/conftest.py,
reset_db esplicito per isolare ogni test). Le righe usano uuid4 per non
collidere tra run.
"""
import uuid

import pytest

from src.core.db.repository import CoreRepository
from src.whatsapp.repository import Repository


async def _seed_org(pg_pool, name):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, $2)", org_id, name
        )
    return org_id


async def _seed_contact(pg_pool, org_id):
    contact_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, $3)",
            contact_id, org_id, f"+39{uuid.uuid4().int % 10**10:010d}",
        )
    return contact_id


async def _seed_conversation(pg_pool, org_id, contact_id):
    conv_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3)",
            conv_id, org_id, contact_id,
        )
    return conv_id


@pytest.fixture
async def two_orgs(pg_pool, reset_db):
    """Due org con contatto + conversazione ciascuna."""
    a = await _seed_org(pg_pool, "Org A")
    b = await _seed_org(pg_pool, "Org B")
    return {
        "a": {"id": a,
              "contact": await _seed_contact(pg_pool, a),
              "conv": await _seed_conversation(pg_pool, a, await _seed_contact(pg_pool, a))},
        "b": {"id": b,
              "contact": await _seed_contact(pg_pool, b),
              "conv": await _seed_conversation(pg_pool, b, await _seed_contact(pg_pool, b))},
    }


# Criticita' #1: update_template_status metteva organization_id nel SET e mai
# nella WHERE: l'update colpiva le righe di TUTTE le org con stesso
# name+language (e tentava il furto di identita' della riga altrui).
async def test_update_template_status_non_sovrascrive_altra_org(two_orgs, pg_pool):
    repo = Repository(pool=pg_pool)
    name = f"promo_{uuid.uuid4().hex[:8]}"
    async with pg_pool.acquire() as conn:
        for org in (two_orgs["a"], two_orgs["b"]):
            await conn.execute(
                """INSERT INTO whatsapp_templates
                       (id, organization_id, name, language, category, status, components)
                   VALUES ($1, $2, $3, 'it', 'MARKETING', 'PENDING', '[]'::jsonb)""",
                uuid.uuid4(), org["id"], name,
            )

    await repo.update_template_status(
        organization_id=two_orgs["a"]["id"],
        name=name,
        language="it",
        status="APPROVED",
    )

    async with pg_pool.acquire() as conn:
        status_a = await conn.fetchval(
            "SELECT status FROM whatsapp_templates WHERE organization_id = $1 AND name = $2 AND language = 'it'",
            two_orgs["a"]["id"], name,
        )
        status_b = await conn.fetchval(
            "SELECT status FROM whatsapp_templates WHERE organization_id = $1 AND name = $2 AND language = 'it'",
            two_orgs["b"]["id"], name,
        )
    assert status_a == "APPROVED"
    assert status_b == "PENDING", (
        "la riga dell'altra organizzazione NON deve essere toccata"
    )


# Criticita' #2: get_conversation filtrava solo per id -> IDOR cross-tenant.
async def test_get_conversation_idor(two_orgs, pg_pool):
    repo = Repository(pool=pg_pool)
    conv_b = two_orgs["b"]["conv"]

    leaked = await repo.get_conversation(str(conv_b), str(two_orgs["a"]["id"]))
    assert leaked is None, "una conversazione di un'altra org NON deve esistere per org_a"

    own = await repo.get_conversation(str(conv_b), str(two_orgs["b"]["id"]))
    assert own is not None
    assert str(own["id"]) == str(conv_b)


# Criticita' #3: fallback SELECT per wam_id senza filtro org -> in caso di
# collisione wam_id la seconda org riceveva la riga della prima.
async def test_upsert_wamid_collision_per_org(two_orgs, pg_pool):
    repo = Repository(pool=pg_pool)
    wam_id = f"wam-collision-{uuid.uuid4().hex[:12]}"
    common = dict(
        direction="inbound",
        message_type="text",
        content={"body": "ciao"},
        content_text="ciao",
        status="received_pending_ai",
    )

    res_a = await repo.upsert_message(
        id=uuid.uuid4(),
        organization_id=two_orgs["a"]["id"],
        conversation_id=two_orgs["a"]["conv"],
        wam_id=wam_id,
        **common,
    )
    assert str(res_a["organization_id"]) == str(two_orgs["a"]["id"])

    res_b = await repo.upsert_message(
        id=uuid.uuid4(),
        organization_id=two_orgs["b"]["id"],
        conversation_id=two_orgs["b"]["conv"],
        wam_id=wam_id,
        **common,
    )
    # La collisione globale su wam_id resta, ma org_b non deve MAI leggere la
    # riga di org_a: o la sua riga, o niente.
    assert res_b is None or str(res_b["organization_id"]) == str(two_orgs["b"]["id"]), (
        f"leak cross-org: org_b ha ricevuto {res_b}"
    )
    if res_b is not None:
        assert str(res_b["id"]) != str(res_a["id"])


# Criticita' #4: get_outbound_dedup senza org -> riga dedup lettabile da
# qualunque org conoscendo il message_id.
async def test_outbound_dedup_scoped(two_orgs, pg_pool):
    repo = Repository(pool=pg_pool)
    message_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO outbound_dedup (message_id, organization_id, response_text)
               VALUES ($1, $2, 'risposta-segreta-org-a')""",
            message_id, two_orgs["a"]["id"],
        )

    other = await repo.get_outbound_dedup(two_orgs["b"]["id"], message_id)
    assert other is None, "il dedup di org_a non deve essere visibile a org_b"

    own = await repo.get_outbound_dedup(two_orgs["a"]["id"], message_id)
    assert own is not None
    assert own["response_text"] == "risposta-segreta-org-a"


# Criticita' #5: dead code cross-tenant rimosso (nessun chiamante in src/).
def test_dead_code_rimosso():
    for method in ("soft_delete_message", "soft_delete_conversation", "soft_delete_contact"):
        assert not hasattr(Repository, method), f"Repository.{method} deve essere rimosso"
    assert not hasattr(CoreRepository, "list_onboarding_profiles"), (
        "CoreRepository.list_onboarding_profiles deve essere rimosso"
    )
