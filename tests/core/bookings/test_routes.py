import os
import pytest
import httpx
from unittest.mock import MagicMock
from src.core.bookings.service import BookingService

API_KEY = "test-api-key-12345"

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def set_env():
    os.environ["DATABASE_URL"] = ""
    os.environ["API_KEY_SERVICE"] = API_KEY


@pytest.fixture
async def async_client(repo, settings, booking_service):
    from src.api.main import app
    app.state.repo = repo
    app.state.pool = MagicMock()
    app.state.booking_service = booking_service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_semaforo_no_auth(async_client):
    resp = await async_client.get("/api/bookings/semaforo")
    assert resp.status_code == 401


async def test_semaforo_authenticated(async_client, sample_org):
    resp = await async_client.get("/api/bookings/semaforo", params={"data": "2026-08-01"}, headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 24


async def test_static_route_before_param(async_client, sample_org):
    # "semaforo" non deve matchare come {booking_id}
    resp = await async_client.get("/api/bookings/semaforo", headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 200


async def test_get_settings(async_client, sample_org):
    resp = await async_client.get("/api/bookings/settings", headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 200
    assert resp.json()["capienze_orarie"]["20:00"] == 40


async def test_create_booking(async_client, sample_org):
    resp = await async_client.post("/api/bookings", json={
        "nome_cliente": "Mario",
        "telefono": "+393331234567",
        "data": "2026-08-01",
        "ora": "20:00",
        "coperti": 4,
    }, headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["stato"] == "in_attesa"
    assert data["nome_cliente"] == "Mario"


async def test_get_booking(async_client, sample_org):
    # Creane una prima
    create_resp = await async_client.post("/api/bookings", json={
        "nome_cliente": "Mario",
        "telefono": "+393331234567",
        "data": "2026-08-01",
        "ora": "20:00",
        "coperti": 4,
    }, headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    b_id = create_resp.json()["id"]

    resp = await async_client.get(f"/api/bookings/{b_id}", headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 200
    assert resp.json()["id"] == b_id


async def test_get_booking_not_found(async_client, sample_org):
    resp = await async_client.get("/api/bookings/00000000-0000-0000-0000-000000000000", headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 404


async def test_confirm_booking(async_client, sample_org):
    create_resp = await async_client.post("/api/bookings", json={
        "nome_cliente": "Mario",
        "telefono": "+393331234567",
        "data": "2026-08-01",
        "ora": "20:00",
        "coperti": 4,
    }, headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    b_id = create_resp.json()["id"]

    resp = await async_client.post(f"/api/bookings/{b_id}/confirm", headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 200
    assert resp.json()["stato"] == "confermata"


async def test_list_bookings(async_client, sample_org):
    await async_client.post("/api/bookings", json={
        "nome_cliente": "Mario",
        "telefono": "+393331234567",
        "data": "2026-08-01",
        "ora": "20:00",
        "coperti": 4,
    }, headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    await async_client.post("/api/bookings", json={
        "nome_cliente": "Luigi",
        "telefono": "+393337654321",
        "data": "2026-08-01",
        "ora": "21:00",
        "coperti": 2,
    }, headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })

    resp = await async_client.get("/api/bookings", params={"data": "2026-08-01"}, headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 200
    assert len(resp.json()) == 2
