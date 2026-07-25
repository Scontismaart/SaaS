import pytest


@pytest.mark.asyncio
async def test_upsert_and_get_settings(repo, sample_org):
    fasce = [f"{h:02d}:00" for h in range(24)]
    capienze = {f: 40 for f in fasce}
    settings = await repo.upsert_booking_settings(
        organization_id=sample_org["id"],
        fasce_orarie=fasce,
        capienze_orarie=capienze,
        slot_minutes=60,
    )
    assert settings["slot_minutes"] == 60
    assert settings["fasce_orarie"] == fasce

    fetched = await repo.get_booking_settings(sample_org["id"])
    assert fetched is not None
    assert fetched["capienze_orarie"]["12:00"] == 40


@pytest.mark.asyncio
async def test_booking_settings_unique_per_org(repo, sample_org):
    fasce = [f"{h:02d}:00" for h in range(24)]
    capienze = {f: 40 for f in fasce}
    await repo.upsert_booking_settings(
        organization_id=sample_org["id"],
        fasce_orarie=fasce, capienze_orarie=capienze,
    )
    await repo.upsert_booking_settings(
        organization_id=sample_org["id"],
        fasce_orarie=fasce, capienze_orarie={f: 30 for f in fasce},
        slot_minutes=30,
    )
    fetched = await repo.get_booking_settings(sample_org["id"])
    assert fetched["slot_minutes"] == 30
    assert fetched["capienze_orarie"]["12:00"] == 30
