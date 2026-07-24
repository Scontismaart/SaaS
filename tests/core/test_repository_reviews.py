import pytest


@pytest.mark.asyncio
async def test_create_and_list_reviews(repo, sample_org):
    review = await repo.create_review(
        organization_id=sample_org["id"],
        testo="Ottimo cibo, personale gentile",
        valutazione_stelle=5,
        fonte="google",
        autore="Mario Rossi",
    )
    assert review["valutazione_stelle"] == 5
    assert review["testo"] == "Ottimo cibo, personale gentile"

    reviews = await repo.list_reviews(sample_org["id"])
    assert len(reviews) == 1


@pytest.mark.asyncio
async def test_review_star_validation(repo, sample_org):
    with pytest.raises(Exception):
        await repo.create_review(
            organization_id=sample_org["id"],
            testo="Bad review",
            valutazione_stelle=6,
        )
