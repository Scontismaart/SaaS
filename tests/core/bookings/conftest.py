from datetime import date, timedelta
import pytest


@pytest.fixture
async def settings(repo, sample_org):
    fasce = [f"{h:02d}:00" for h in range(24)]
    capienze = {f: 40 for f in fasce}
    return await repo.upsert_booking_settings(
        organization_id=sample_org["id"],
        fasce_orarie=fasce, capienze_orarie=capienze,
    )


@pytest.fixture
def booking_service(repo, sample_org, settings):
    from src.core.bookings.service import BookingService
    return BookingService(repo, None, None)


@pytest.fixture
def tomorrow():
    return date.today() + timedelta(days=1)
