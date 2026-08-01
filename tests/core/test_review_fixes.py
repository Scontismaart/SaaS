import asyncio

import asyncpg
import pytest

from src.core.priorita import calcola_priorita_recensione
from src.models.schemas import RispostaRecensioneOutput

pytestmark = pytest.mark.usefixtures("reset_db")


# ---------------------------------------------------------------------------
# Fix: dedup su external_id (constraint UNIQUE(organization_id, external_id))
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_external_id_same_org_raises_unique_violation(repo, sample_org):
    await repo.create_review(
        organization_id=sample_org["id"],
        testo="Prima recensione",
        valutazione_stelle=4,
        fonte="google",
        external_id="google-rev-123",
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await repo.create_review(
            organization_id=sample_org["id"],
            testo="Stessa recensione ri-fetchata",
            valutazione_stelle=4,
            fonte="google",
            external_id="google-rev-123",
        )


@pytest.mark.asyncio
async def test_duplicate_external_id_different_org_is_allowed(repo, sample_org, other_org):
    await repo.create_review(
        organization_id=sample_org["id"],
        testo="Recensione org A",
        fonte="google",
        external_id="google-rev-999",
    )
    # Stesso external_id ma org diversa: non deve collidere (dedup e' per-org)
    review = await repo.create_review(
        organization_id=other_org["id"],
        testo="Recensione org B",
        fonte="google",
        external_id="google-rev-999",
    )
    assert review["organization_id"] == other_org["id"]


@pytest.mark.asyncio
async def test_get_review_by_external_id_used_for_dedup_reuse(repo, sample_org):
    created = await repo.create_review(
        organization_id=sample_org["id"],
        testo="Originale",
        fonte="google",
        external_id="google-rev-abc",
    )
    found = await repo.get_review_by_external_id(sample_org["id"], "google-rev-abc")
    assert found["id"] == created["id"]



# ---------------------------------------------------------------------------
# Fix: update_review whitelist (niente nomi colonna arbitrari in SQL)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_review_rejects_unknown_field(repo, sample_org):
    review = await repo.create_review(
        organization_id=sample_org["id"],
        testo="Recensione da modificare",
        fonte="manuale",
    )
    with pytest.raises(ValueError):
        await repo.update_review(
            sample_org["id"], review["id"],
            contact_id="iniettato",
        )


@pytest.mark.asyncio
async def test_update_review_accepts_whitelisted_field(repo, sample_org):
    review = await repo.create_review(
        organization_id=sample_org["id"],
        testo="Recensione da modificare",
        fonte="manuale",
    )
    updated = await repo.update_review(
        sample_org["id"], review["id"], stato="approvata",
    )
    assert updated["stato"] == "approvata"



# ---------------------------------------------------------------------------
# Fix: approve_review con FOR UPDATE dentro una transazione reale
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_review_idempotent_when_already_pubblicata(repo, sample_org):
    review = await repo.create_review(
        organization_id=sample_org["id"],
        testo="Recensione da approvare",
        fonte="manuale",
    )
    await repo.update_review(sample_org["id"], review["id"], stato="pubblicata")

    result = await repo.approve_review(sample_org["id"], review["id"])
    # Non deve regredire una recensione gia' pubblicata a 'approvata'
    assert result["stato"] == "pubblicata"


@pytest.mark.asyncio
async def test_approve_review_returns_none_for_wrong_org(repo, sample_org, other_org):
    review = await repo.create_review(
        organization_id=sample_org["id"],
        testo="Recensione di org A",
        fonte="manuale",
    )
    result = await repo.approve_review(other_org["id"], review["id"])
    assert result is None


@pytest.mark.asyncio
async def test_approve_review_concurrent_double_click_ends_consistent(repo, sample_org):
    review = await repo.create_review(
        organization_id=sample_org["id"],
        testo="Recensione cliccata due volte",
        fonte="manuale",
        stato="bozza_generata",
    )
    # Simula due click "approva" quasi simultanei: con FOR UPDATE dentro una
    # transazione reale, il secondo aspetta il primo invece di correre in
    # parallelo su una lettura stale (prima del fix il lock non serviva a
    # niente fuori da una transazione esplicita).
    risultati = await asyncio.gather(
        repo.approve_review(sample_org["id"], review["id"]),
        repo.approve_review(sample_org["id"], review["id"]),
    )
    assert all(r is not None for r in risultati)
    assert all(r["stato"] == "approvata" for r in risultati)

    finale = await repo.get_review(sample_org["id"], review["id"])
    assert finale["stato"] == "approvata"



# ---------------------------------------------------------------------------
# Fix: trigger DB allineato a calcola_priorita_recensione (niente piu'
# doppia fonte di verita' tra event_log e _storico_eventi)
# ---------------------------------------------------------------------------

CASI_PRIORITA = [
    # (stelle, sentiment, richiede_revisione_urgente, priorita_attesa)
    (1, "negativa", False, "alta"),
    (2, "neutra", False, "alta"),
    (4, "positiva", True, "alta"),          # urgente vince anche con stelle alte
    (5, "negativa", False, "media"),
    (3, "neutra", False, "media"),
    (3, "positiva", False, "bassa"),        # 3 stelle ma sentiment positivo
    (5, "positiva", False, "bassa"),
    (4, "neutra", False, "bassa"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("stelle,sentiment,urgente,attesa", CASI_PRIORITA)
async def test_trigger_priorita_allineata_a_logica_python(
    repo, sample_org, stelle, sentiment, urgente, attesa,
):
    output = RispostaRecensioneOutput(
        id="ignorato", stato="bozza_generata",
        bozza_risposta="bozza", sentiment=sentiment,
        richiede_revisione_urgente=urgente,
        motivo="test", categoria="generico",
    )
    # La logica Python e' il riferimento: il trigger deve produrre lo stesso
    # risultato per lo stesso input, altrimenti dashboard diverse mostrano
    # priorita' diverse per la stessa recensione.
    assert calcola_priorita_recensione(stelle, output).value == attesa

    review = await repo.create_review(
        organization_id=sample_org["id"],
        testo="Recensione di test",
        valutazione_stelle=stelle,
        fonte="google",
        sentiment=sentiment,
        richiede_revisione_urgente=urgente,
    )
    async with repo.pool.acquire() as conn:
        evento = await conn.fetchrow(
            "SELECT priorita FROM event_log WHERE source_table = 'reviews' AND source_id = $1",
            review["id"],
        )
    assert evento["priorita"] == attesa
