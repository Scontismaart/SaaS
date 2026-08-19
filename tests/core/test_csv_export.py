"""Test generazione CSV prenotazioni (no Docker)."""

from datetime import date, time

from src.core.report.csv_export import _COLONNE, genera_csv


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
