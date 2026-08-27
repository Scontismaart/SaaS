"""Test generazione CSV prenotazioni (no Docker)."""

import uuid
import pytest
from datetime import date, time, timedelta, datetime

from src.core.report.csv_export import _COLONNE, genera_csv, get_prenotazioni_completate


def test_csv_header_corretto():
    """Il CSV contiene le colonne attese."""
    csv_bytes = genera_csv([])
    testo = csv_bytes.decode("utf-8-sig")  # Rimuove BOM
    header = testo.strip().split("\n")[0]
    assert header == ",".join(_COLONNE)


def test_csv_bom_presente():
    """Il CSV inizia con BOM UTF-8 per Excel."""
    csv_bytes = genera_csv([])
    assert csv_bytes[:3] == b"\xef\xbb\xbf"


def test_csv_con_dati():
    """CSV con prenotazioni: righe corrette e valori formattati."""
    prenotazioni = [
        {
            "data": date(2026, 8, 15),
            "ora": time(19, 30),
            "coperti": 4,
            "nome_cliente": "Mario Rossi",
            "stato": "completata",
        },
        {
            "data": date(2026, 8, 16),
            "ora": time(20, 0),
            "coperti": 2,
            "nome_cliente": "Anna Verdi",
            "stato": "completata",
        },
    ]

    csv_bytes = genera_csv(prenotazioni)
    testo = csv_bytes.decode("utf-8-sig")
    righe = testo.strip().split("\n")

    assert len(righe) == 3  # header + 2 righe dati
    assert "Mario Rossi" in righe[1]
    assert "Anna Verdi" in righe[2]
    assert "2026-08-15" in righe[1]
    assert "completata" in righe[1]


def test_csv_valori_none():
    """Valori None vengono convertiti in stringa vuota."""
    prenotazioni = [
        {
            "data": date(2026, 8, 15),
            "ora": None,
            "coperti": None,
            "nome_cliente": "",
            "stato": "completata",
        },
    ]

    csv_bytes = genera_csv(prenotazioni)
    testo = csv_bytes.decode("utf-8-sig")
    righe = testo.strip().split("\n")

    assert len(righe) == 2
    # Nessuna eccezione, i None sono stringhe vuote
    assert "2026-08-15" in righe[1]


def test_csv_encoding_utf8():
    """Caratteri speciali (accenti, emoji) gestiti correttamente."""
    prenotazioni = [
        {
            "data": date(2026, 8, 15),
            "ora": time(20, 0),
            "coperti": 6,
            "nome_cliente": "José García Müller",
            "stato": "completata",
        },
    ]

    csv_bytes = genera_csv(prenotazioni)
    testo = csv_bytes.decode("utf-8-sig")
    assert "José García Müller" in testo


@pytest.mark.asyncio
async def test_filtro_data_servizio_non_created_at(pg_pool):
    """Export deve usare data servizio, non created_at."""
    org_id = uuid.uuid4()
    domani = date.today() + timedelta(days=1)

    async with pg_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO organizations (id, name)
            VALUES ($1, 'Test')
        """, org_id)

        # Prenotazione per domani, creata OGGI, stato confermata
        await conn.execute("""
            INSERT INTO bookings (organization_id, nome_cliente, data, ora, coperti, stato, created_at)
            VALUES ($1, 'Cliente Domani', $2, '20:00', 4, 'confermata', NOW())
        """, org_id, domani)

        # Prenotazione per oggi, creata IERI, stato completata
        await conn.execute("""
            INSERT INTO bookings (organization_id, nome_cliente, data, ora, coperti, stato, created_at)
            VALUES ($1, 'Cliente Oggi', $2, '19:00', 2, 'completata', NOW() - INTERVAL '2 days')
        """, org_id, date.today())

    # Query con stati=['confermata'] per domani: deve restituire la prenotazione di domani
    risultati = await get_prenotazioni_completate(
        pg_pool, str(org_id), domani, domani, stati=["confermata"]
    )
    assert len(risultati) == 1
    assert risultati[0]["nome_cliente"] == "Cliente Domani"
    assert risultati[0]["stato"] == "confermata"
    assert risultati[0]["data"] == domani

    # Query default (solo completata): deve restituire la prenotazione di oggi
    risultati_default = await get_prenotazioni_completate(
        pg_pool, str(org_id), date.today(), date.today()
    )
    assert len(risultati_default) == 1
    assert risultati_default[0]["nome_cliente"] == "Cliente Oggi"
    assert risultati_default[0]["stato"] == "completata"

    # Query con entrambi gli stati
    risultati_entrambi = await get_prenotazioni_completate(
        pg_pool, str(org_id), date.today(), domani, stati=["confermata", "completata"]
    )
    assert len(risultati_entrambi) == 2
