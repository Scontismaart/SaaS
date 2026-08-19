"""Rotazione ENCRYPTION_KEY (debito audit): lo script
scripts/rotate_encryption_key.py ri-cifra le credenziali a riposo in
un'unica transazione con backup. Qui lo testiamo contro il Postgres reale
di test: rotazione, dry-run, verifica e rollback su dato corrotto."""

import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet, InvalidToken

pytestmark = pytest.mark.usefixtures("reset_db")

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rotate_encryption_key.py"


def _carica_script():
    spec = importlib.util.spec_from_file_location("rotate_encryption_key", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _chiavi():
    return (
        Fernet.generate_key().decode(),
        Fernet.generate_key().decode(),
    )


async def _popola(pg_pool, conn, vecchia: str, org_id: uuid.UUID) -> None:
    cipher = Fernet(vecchia.encode())
    cifra = lambda s: cipher.encrypt(s.encode()).decode()
    now = datetime.now(timezone.utc)
    await conn.execute(
        "INSERT INTO organizations (id, name) VALUES ($1, 'Rotation-Test')",
        org_id,
    )
    await conn.execute(
        "INSERT INTO whatsapp_accounts "
        "(id, organization_id, phone_number_id, waba_id, access_token) "
        "VALUES ($1, $2, $3, $4, $5)",
        uuid.uuid4(), org_id, "phone-1", "waba-1", cifra("wa-token"),
    )
    await conn.execute(
        "INSERT INTO instagram_accounts "
        "(id, organization_id, ig_user_id, access_token) "
        "VALUES ($1, $2, $3, $4)",
        uuid.uuid4(), org_id, "ig-user-1", cifra("ig-token"),
    )
    await conn.execute(
        "INSERT INTO google_calendar_credentials "
        "(organization_id, access_token, refresh_token, token_expiry) "
        "VALUES ($1, $2, $3, $4)",
        org_id, cifra("gc-at"), cifra("gc-rt"), now,
    )
    await conn.execute(
        "INSERT INTO google_business_credentials "
        "(organization_id, access_token, refresh_token, token_expiry) "
        "VALUES ($1, $2, $3, $4)",
        org_id, cifra("gb-at"), cifra("gb-rt"), now,
    )


async def _valori_cifrati(conn, mod):
    """(tabella.colonna, valore_cifrato) per tutte le righe Fernet presenti."""
    coppie = []
    for tabella, _pk, colonne in mod.TABELLE:
        cols = ", ".join(colonne)
        righe = await conn.fetch(f"SELECT {cols} FROM {tabella}")
        for riga in righe:
            for col in colonne:
                coppie.append((f"{tabella}.{col}", riga[col]))
    return coppie


def _decripta_tutte(coppie, chiave: str) -> None:
    cipher = Fernet(chiave.encode())
    for nome, valore in coppie:
        assert valore != "garbage", f"{nome} e' il valore corrotto del rollback"
        cipher.decrypt(valore.encode())


def _con_chiave_sbagliata_deve_fallire(coppie, chiave: str) -> None:
    cipher = Fernet(chiave.encode())
    for nome, valore in coppie:
        with pytest.raises(InvalidToken):
            cipher.decrypt(valore.encode())


class TestRotazione:
    @pytest_asyncio.fixture
    async def setup(self, pg_pool):
        vecchia, nuova = _chiavi()
        async with pg_pool.acquire() as conn:
            org_id = uuid.uuid4()
            await _popola(pg_pool, conn, vecchia, org_id)
        return {"vecchia": vecchia, "nuova": nuova}

    async def test_rotazione_ricifra_con_la_nuova_chiave(self, pg_pool, setup, tmp_path):
        mod = _carica_script()
        async with pg_pool.acquire() as conn:
            await mod._ruota(conn, setup["vecchia"], setup["nuova"],
                             dry_run=False, backup_dir=str(tmp_path))
            coppie = await _valori_cifrati(conn, mod)
        assert len(coppie) == 6  # 1 wa + 1 ig + 2 google*2
        _decripta_tutte(coppie, setup["nuova"])
        _con_chiave_sbagliata_deve_fallire(coppie, setup["vecchia"])

    async def test_backup_scritto_prima_della_rotazione(self, pg_pool, setup, tmp_path):
        mod = _carica_script()
        async with pg_pool.acquire() as conn:
            await mod._ruota(conn, setup["vecchia"], setup["nuova"],
                             dry_run=False, backup_dir=str(tmp_path))
        backup = list(tmp_path.glob("rotate_encryption_key_*.json"))
        assert len(backup) == 1
        assert "whatsapp_accounts" in backup[0].read_text(encoding="utf-8")

    async def test_dry_run_non_modifica_il_db(self, pg_pool, setup, tmp_path):
        mod = _carica_script()
        async with pg_pool.acquire() as conn:
            await mod._ruota(conn, setup["vecchia"], setup["nuova"],
                             dry_run=True, backup_dir=str(tmp_path))
            coppie = await _valori_cifrati(conn, mod)
        _decripta_tutte(coppie, setup["vecchia"])
        assert list(tmp_path.glob("rotate_encryption_key_*.json")) == []

    async def test_verifica_con_chiave_giusta(self, pg_pool, setup, tmp_path):
        mod = _carica_script()
        async with pg_pool.acquire() as conn:
            await mod._ruota(conn, setup["vecchia"], setup["nuova"],
                             dry_run=False, backup_dir=str(tmp_path))
            totale = await mod._verifica(conn, setup["nuova"])
        assert totale == 4  # 4 tabelle x 1 riga ciascuna (ogni colonna verificata)

    async def test_verifica_con_chiave_sbagliata_fallisce(self, pg_pool, setup, tmp_path):
        mod = _carica_script()
        async with pg_pool.acquire() as conn:
            await mod._ruota(conn, setup["vecchia"], setup["nuova"],
                             dry_run=False, backup_dir=str(tmp_path))
            with pytest.raises(SystemExit):
                await mod._verifica(conn, setup["vecchia"])

    async def test_dato_corrotto_fa_rollback_e_non_lascia_mezzine(self, pg_pool, tmp_path):
        mod = _carica_script()
        vecchia, nuova = _chiavi()
        async with pg_pool.acquire() as conn:
            org_id = uuid.uuid4()
            await _popola(pg_pool, conn, vecchia, org_id)
            await conn.execute(
                "UPDATE google_calendar_credentials SET access_token = 'garbage' "
                "WHERE organization_id = $1",
                org_id,
            )
            with pytest.raises(InvalidToken):
                await mod._ruota(conn, vecchia, nuova,
                                 dry_run=False, backup_dir=str(tmp_path))
            # rollback: TUTTE le righe sane restano decifrabili con la vecchia chiave
            coppie = [
                (nome, val) for nome, val in await _valori_cifrati(conn, mod)
                if val != "garbage"
            ]
        _decripta_tutte(coppie, vecchia)
        _con_chiave_sbagliata_deve_fallire(coppie, nuova)