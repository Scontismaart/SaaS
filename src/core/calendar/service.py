import asyncio
import os
import logging
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
DEFAULT_SLOT_MINUTES = 60


class GoogleCalendarService:
    def __init__(self, repo, encryption_key):
        self.repo = repo
        if not encryption_key:
            raise ValueError(
                "ENCRYPTION_KEY mancante: richiesto per cifrare i token OAuth Google. "
                "Genera una chiave con `python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
                "e impostala in .env."
            )
        self.fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock_init = asyncio.Lock()

    async def _get_org_lock(self, org_id):
        async with self._lock_init:
            if org_id not in self._locks:
                self._locks[org_id] = asyncio.Lock()
            return self._locks[org_id]

    def _decrypt(self, value: str) -> str:
        return self.fernet.decrypt(value.encode()).decode()

    def _encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode()).decode()

    def encrypt_secret(self, value: str) -> str:
        # API pubblica per routes.py (OAuth callback) — crittografa token
        # prima di scriverli su DB. _get_credentials assume che siano
        # Fernet-encrypted, quindi ogni scrittura DEVE passare di qui.
        return self._encrypt(value)

    def _get_client_config(self):
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise RuntimeError(
                "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET mancanti in env: "
                "impossibile operare con le API Google."
            )
        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "token_uri": "https://oauth2.googleapis.com/token",
        }

    async def _get_credentials(self, org_id):
        async with await self._get_org_lock(org_id):
            async with self.repo.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM google_calendar_credentials WHERE organization_id = $1",
                    org_id,
                )
                if not row:
                    return None
                try:
                    cfg = self._get_client_config()
                except RuntimeError as e:
                    logger.warning("calendar=no_client_config org_id=%s err=%s", org_id, e)
                    return None
                # Postgres TIMESTAMPTZ ritorna datetime tz-aware via asyncpg,
                # ma google Credentials.expired lo confronta con utcnow() naive.
                # Normalizziamo a naive UTC per evitare TypeError al confronto.
                expiry = row["token_expiry"]
                if expiry and getattr(expiry, "tzinfo", None) is not None:
                    expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
                creds = Credentials(
                    token=self._decrypt(row["access_token"]),
                    refresh_token=self._decrypt(row["refresh_token"]),
                    token_uri=cfg["token_uri"],
                    client_id=cfg["client_id"],
                    client_secret=cfg["client_secret"],
                    scopes=SCOPES,
                    expiry=expiry,
                )
                if creds.expired and creds.refresh_token:
                    try:
                        await asyncio.to_thread(creds.refresh, GoogleAuthRequest())
                        await conn.execute(
                            """UPDATE google_calendar_credentials
                               SET access_token = $2, token_expiry = $3, updated_at = NOW()
                               WHERE organization_id = $1""",
                            org_id,
                            self._encrypt(creds.token),
                            creds.expiry,
                        )
                    except RefreshError:
                        logger.error("calendar=token_revoked org_id=%s", org_id)
                        await conn.execute(
                            """UPDATE google_calendar_credentials
                               SET sync_enabled = false, updated_at = NOW()
                               WHERE organization_id = $1""",
                            org_id,
                        )
                        return None
            return creds

    async def _get_calendar_id(self, org_id):
        async with self.repo.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT calendar_id FROM google_calendar_credentials WHERE organization_id = $1",
                org_id,
            )
            return row["calendar_id"] if row else "primary"

    async def _get_org_timezone(self, org_id):
        async with self.repo.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT timezone FROM organizations WHERE id = $1", org_id
            )
            return row["timezone"] if row else "Europe/Rome"

    async def _build_service(self, org_id):
        creds = await self._get_credentials(org_id)
        if not creds:
            return None
        return await asyncio.to_thread(build, "calendar", "v3", credentials=creds)

    async def create_event(self, booking, org_id):
        service = await self._build_service(org_id)
        if not service:
            return None
        calendar_id = await self._get_calendar_id(org_id)
        tz = await self._get_org_timezone(org_id)

        data = booking["data"]
        ora = booking["ora"]
        data_str = data.isoformat() if hasattr(data, "isoformat") else str(data)
        ora_str = ora.strftime("%H:%M:%S") if hasattr(ora, "strftime") else str(ora)

        start_dt = datetime.fromisoformat(f"{data_str}T{ora_str}")
        end_dt = start_dt + timedelta(minutes=DEFAULT_SLOT_MINUTES)

        event_body = {
            "summary": f"{booking['nome_cliente']} \u2014 {booking['coperti']} coperti",
            "description": (
                f"Booking ID: {booking['id']}\n"
                f"Cliente: {booking['nome_cliente']}\n"
                f"Telefono: {booking['telefono']}\n"
                f"Coperti: {booking['coperti']}\n"
                f"Note: {booking.get('note', '')}\n"
                f"Stato: {booking['stato']}\n"
                f"Origine: {booking.get('origine', '')}"
            ),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
        }

        created = await asyncio.to_thread(
            service.events().insert(calendarId=calendar_id, body=event_body).execute
        )
        event_id = created["id"]
        try:
            async with self.repo.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE bookings SET google_event_id = $2, updated_at = NOW() "
                    "WHERE organization_id = $3 AND id = $1",
                    booking["id"],
                    event_id,
                    org_id,
                )
        except Exception:
            logger.exception(
                "calendar=event_created_db_fail booking_id=%s org_id=%s event_id=%s",
                booking["id"], org_id, event_id,
            )
        return event_id

    async def update_event(self, booking, org_id):
        event_id = booking.get("google_event_id")
        if not event_id:
            return None
        service = await self._build_service(org_id)
        if not service:
            return None
        calendar_id = await self._get_calendar_id(org_id)
        tz = await self._get_org_timezone(org_id)

        data = booking["data"]
        ora = booking["ora"]
        data_str = data.isoformat() if hasattr(data, "isoformat") else str(data)
        ora_str = ora.strftime("%H:%M:%S") if hasattr(ora, "strftime") else str(ora)

        start_dt = datetime.fromisoformat(f"{data_str}T{ora_str}")
        end_dt = start_dt + timedelta(minutes=DEFAULT_SLOT_MINUTES)

        body = {
            "summary": f"{booking['nome_cliente']} \u2014 {booking['coperti']} coperti",
            "description": (
                f"Booking ID: {booking['id']}\n"
                f"Cliente: {booking['nome_cliente']}\n"
                f"Telefono: {booking['telefono']}\n"
                f"Coperti: {booking['coperti']}\n"
                f"Note: {booking.get('note', '')}\n"
                f"Stato: {booking['stato']}\n"
                f"Origine: {booking.get('origine', '')}"
            ),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
        }
        try:
            await asyncio.to_thread(
                service.events().update(calendarId=calendar_id, eventId=event_id, body=body).execute
            )
        except Exception:
            logger.exception(
                "calendar=event_update_fail booking_id=%s org_id=%s event_id=%s",
                booking["id"], org_id, event_id,
            )
        return event_id

    async def delete_event(self, booking, org_id):
        event_id = booking.get("google_event_id")
        if not event_id:
            return None
        service = await self._build_service(org_id)
        if not service:
            return None
        calendar_id = await self._get_calendar_id(org_id)
        try:
            await asyncio.to_thread(
                service.events().delete(calendarId=calendar_id, eventId=event_id).execute
            )
        except Exception:
            logger.exception(
                "calendar=event_delete_fail booking_id=%s org_id=%s event_id=%s",
                booking["id"], org_id, event_id,
            )
        async with self.repo.pool.acquire() as conn:
            await conn.execute(
                "UPDATE bookings SET google_event_id = NULL, updated_at = NOW() "
                "WHERE organization_id = $2 AND id = $1",
                booking["id"],
                org_id,
            )
        return event_id

    async def sync_booking_state(self, booking, org_id):
        stato = booking.get("stato", "")
        google_event_id = booking.get("google_event_id")
        stato_occupato = {"in_attesa", "confermata", "da_verificare", "completata"}
        stato_finale = {"cancellata", "cancellato", "rifiutata", "no_show"}

        try:
            if stato in stato_occupato:
                if not google_event_id:
                    await self.create_event(booking, org_id)
                else:
                    await self.update_event(booking, org_id)
            elif stato in stato_finale:
                if google_event_id:
                    await self.delete_event(booking, org_id)
        except Exception:
            logger.exception(
                "calendar=sync_fail booking_id=%s org_id=%s stato=%s",
                booking.get("id"), org_id, stato,
            )
