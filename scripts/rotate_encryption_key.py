#!/usr/bin/env python3
"""Rotazione della ENCRYPTION_KEY (Fernet) per le credenziali a riposo.

Ri-cifra in-place le colonne Fernet-encrypted del multi-tenant:

    whatsapp_accounts.access_token
    instagram_accounts.access_token
    google_calendar_credentials.access_token, refresh_token
    google_business_credentials.access_token, refresh_token

Uso:
  python scripts/rotate_encryption_key.py --new-key "<FERNET_KEY>" --dry-run
  python scripts/rotate_encryption_key.py --new-key "<FERNET_KEY>"
  python scripts/rotate_encryption_key.py --verify "<FERNET_KEY>"

La vecchia chiave viene letta da ENCRYPTION_KEY (override con --old-key).
Prima di scrivere viene salvato un backup JSON dei valori cifrati correnti.
L'intera operazione gira in un'unica transazione: se una riga non si decifra
con la vecchia chiave (chiave sbagliata o dati corrotti) scatta il rollback e
nessuna riga resta parzialmente rotata.

Ordine CORRETTO per la rotazione:
  1. genera la nuova chiave:
       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. esegui questo script con --new-key (i dati restano cifrati, ma si
     decifrano solo con la NUOVA chiave -> piccolo maintenance window);
  3. aggiorna ENCRYPTION_KEY nel .env / secrets manager con la NUOVA chiave
     e fai il deploy (questo chiude la finestra);
  4. verifica che tutto si decifri con la nuova chiave: --verify.

Alternativa senza finestra (consigliata in produzione): scrivi un'istanza
extra dell'app con la NUOVA ENCRYPTION_KEY, poi falla rotare i dati con lo
script puntando al DB condiviso, poi spegni la vecchia istanza.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from cryptography.fernet import Fernet, InvalidToken

# (tabella, colonna PK, [colonne Fernet-encrypted])
TABELLE = [
    ("whatsapp_accounts", "id", ["access_token"]),
    ("instagram_accounts", "id", ["access_token"]),
    ("google_calendar_credentials", "organization_id", ["access_token", "refresh_token"]),
    ("google_business_credentials", "organization_id", ["access_token", "refresh_token"]),
]


def _print(msg: str) -> None:
    print(msg, flush=True)


def _fernet(key: str) -> Fernet:
    return Fernet(key.encode())


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--new-key", help="Nuova chiave Fernet (base64).")
    p.add_argument("--old-key", help="Vecchia chiave Fernet. Default: env ENCRYPTION_KEY.")
    p.add_argument("--verify", metavar="KEY",
                   help="Modalita' verifica: controlla che tutte le righe si decifrino con KEY.")
    p.add_argument("--dsn", help="PostgreSQL DSN. Default: env DATABASE_URL o POSTGRES_DSN.")
    p.add_argument("--dry-run", action="store_true",
                   help="Mostra cosa verrebbe rotato senza scrivere ne' fare backup.")
    p.add_argument("--backup-dir", default="backups",
                   help="Cartella del backup JSON (default: backups/).")
    return p.parse_args()


async def _select_righe(conn, tabella: str, colonna_pk: str, colonne: list[str]) -> list[dict]:
    cols = ", ".join([colonna_pk, *colonne])
    rows = await conn.fetch(f"SELECT {cols} FROM {tabella} ORDER BY {colonna_pk}")
    return [dict(r) for r in rows]


def _scrivi_backup(backup_dir: str, righe_per_tabella: dict[str, list[dict]],
                   colonne_per_tabella: dict[str, list[str]]) -> str:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stampa = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    percorso = backup_dir / f"rotate_encryption_key_{stampa}.json"
    payload = {
        "generato": datetime.now(timezone.utc).isoformat(),
        "chiave_old": "<redatto>",
        "tabelle": {
            tab: {
                "colonne_cifrate": colonne_per_tabella[tab],
                "righe": righe,
            }
            for tab, righe in righe_per_tabella.items()
        },
    }
    percorso.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    return str(percorso)


async def _verifica(conn, chiave: str) -> int:
    _print(f"[verify] Chiave: {chiave[:12]}... (truncata)")
    cipher = _fernet(chiave)
    totale = 0
    for tabella, colonna_pk, colonne in TABELLE:
        righe = await _select_righe(conn, tabella, colonna_pk, colonne)
        for riga in righe:
            for col in colonne:
                valore = riga.get(col)
                if not valore:
                    continue
                try:
                    cipher.decrypt(valore.encode())
                except InvalidToken:
                    sys.exit(
                        f"[verify] FALLITA decifratura: {tabella}.{col} pk={riga[colonna_pk]}. "
                        "La chiave non e' quella giusta o il dato e' corrotto."
                    )
        totale += len(righe)
        _print(f"[verify] OK  {tabella}: {len(righe)} righe")
    _print(f"[verify] Tutte le {totale} righe si decifrano con la chiave data.")
    return totale


async def _ruota(conn, vecchia: str, nuova: str, dry_run: bool, backup_dir: str) -> None:
    vecchio = _fernet(vecchia)
    nuovo = _fernet(nuova)
    _print(f"[rotate] Vecchia chiave: {vecchia[:12]}... (truncata)")
    _print(f"[rotate] Nuova chiave:   {nuova[:12]}... (truncata)")
    _print(f"[rotate] Dry-run: {dry_run}")

    righe_per_tabella: dict[str, list[dict]] = {}
    colonne_per_tabella: dict[str, list[str]] = {}
    for tabella, colonna_pk, colonne in TABELLE:
        righe = await _select_righe(conn, tabella, colonna_pk, colonne)
        righe_per_tabella[tabella] = righe
        colonne_per_tabella[tabella] = colonne
        _print(f"[rotate] Lette {len(righe)} righe da {tabella}")

    if dry_run:
        _print("[rotate] Dry-run: nessuna scrittura. Ecco cosa verrebbe rotato:")
        for tabella, righe in righe_per_tabella.items():
            colonne = colonne_per_tabella[tabella]
            _print(f"  - {tabella}: {len(righe)} righe x {colonne}")
        return

    percorso = _scrivi_backup(backup_dir, righe_per_tabella, colonne_per_tabella)
    _print(f"[rotate] Backup scritto: {percorso}")

    async with conn.transaction():
        for tabella, colonna_pk, colonne in TABELLE:
            aggiornate = 0
            for riga in righe_per_tabella[tabella]:
                set_clausole = []
                valori: list = []  # prima i valori cifrati, poi il PK
                for col in colonne:
                    valore = riga.get(col)
                    if not valore:
                        continue
                    decifrato = vecchio.decrypt(valore.encode())  # InvalidToken -> rollback
                    ricifrato = nuovo.encrypt(decifrato).decode()
                    set_clausole.append(f"{col} = ${len(valori) + 1}")
                    valori.append(ricifrato)
                if not set_clausole:
                    continue
                valori.append(riga[colonna_pk])
                query = (
                    f"UPDATE {tabella} SET {', '.join(set_clausole)}, updated_at = NOW() "
                    f"WHERE {colonna_pk} = ${len(valori)}"
                )
                await conn.execute(query, *valori)
                aggiornate += 1
            _print(f"[rotate] Aggiornate {aggiornate} righe su {tabella}")
    _print("[rotate] Rotazione completata (committed).")


async def main():
    args = _parse_args()
    if args.verify:
        dsn = args.dsn or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
        if not dsn:
            sys.exit("Nessun DSN: imposta DATABASE_URL o usa --dsn.")
        conn = await asyncpg.connect(dsn)
        try:
            await _verifica(conn, args.verify)
        finally:
            await conn.close()
        return

    if not args.new_key:
        sys.exit("Serve --new-key (o usa --verify).")
    vecchia = args.old_key or os.getenv("ENCRYPTION_KEY")
    if not vecchia:
        sys.exit("Vecchia chiave mancante: imposta ENCRYPTION_KEY o usa --old-key.")
    if vecchia == args.new_key:
        sys.exit("La nuova chiave coincide con la vecchia: nessuna rotazione.")
    dsn = args.dsn or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        sys.exit("Nessun DSN: imposta DATABASE_URL o usa --dsn.")
    conn = await asyncpg.connect(dsn)
    try:
        await _ruota(conn, vecchia, args.new_key, args.dry_run, args.backup_dir)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())