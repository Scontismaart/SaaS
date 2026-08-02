import asyncio
import logging
import os
from datetime import timezone

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError

logger = logging.getLogger(__name__)

# Scope per gestire recensioni e dati del profilo Business.
SCOPES = ["https://www.googleapis.com/auth/business.manage"]
REVIEWS_TABLE = "google_business_credentials"
STAR_RATING_MAP = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}


class GoogleBusinessService:
    """Client per le recensioni di Google Business Profile.

    Simmetrico a GoogleCalendarService: token cifrati con Fernet a riposo,
    refresh automatico del token scaduto, lock per-org contro refresh
    concorrenti. La chiamata di rete e' isolata in _list_reviews cosi' i
    test la mockano senza toccare l'API reale.
    """

    def __init__(self, repo, encryption_key):
        self.repo = repo
        if not encryption_key:
            raise ValueError(
                "ENCRYPTION_KEY mancante: richiesto per cifrare i token "
                "OAuth Google Business. Impostala in .env."
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
        return self._encrypt(value)

    def _get_client_config(self):
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise RuntimeError(
                "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET mancanti in env."
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
                    f"SELECT * FROM {REVIEWS_TABLE} WHERE organization_id = $1",
                    org_id,
                )
                if not row:
                    return None
                try:
                    cfg = self._get_client_config()
                except RuntimeError as e:
                    logger.warning("business=no_client_config org_id=%s err=%s", org_id, e)
                    return None
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
                            f"""UPDATE {REVIEWS_TABLE}
                                SET access_token = $2, token_expiry = $3, updated_at = NOW()
                                WHERE organization_id = $1""",
                            org_id,
                            self._encrypt(creds.token),
                            creds.expiry,
                        )
                    except RefreshError:
                        logger.error("business=token_revoked org_id=%s", org_id)
                        await conn.execute(
                            f"UPDATE {REVIEWS_TABLE} SET updated_at = NOW() WHERE organization_id = $1",
                            org_id,
                        )
                        return None
            return creds

    async def _build_service(self, org_id):
        creds = await self._get_credentials(org_id)
        if not creds:
            return None
        # Google Business Profile (ex "My Business") non e' nel discovery
        # statico bundled di googleapiclient: static_discovery=False forza il
        # fetch remoto del discovery doc. My Business API v4: le review
        # vivono in accounts/{account}/locations/{location}/reviews.
        return await asyncio.to_thread(
            build, "mybusiness", "v4", credentials=creds, static_discovery=False
        )

    async def _list_reviews(self, service, account_name, location_name, page_size=50):
        """Chiamata di rete isolata — mockata nei test.

        Ritorna le review grezze come restituite dall'API (dict). La firma
        prende service + identificativi cosi' i test costruiscono un fake
        senza passare per build().
        """
        result = await asyncio.to_thread(
            service.accounts().locations().reviews()
            .list(accountsId=account_name, locationsId=location_name, pageSize=page_size)
            .execute
        )
        return result.get("reviews", [])

    def _map_review(self, raw: dict) -> dict:
        comment = raw.get("comment", {}) or {}
        reviewer = raw.get("reviewer", {}) or {}
        star = STAR_RATING_MAP.get(raw.get("starRating", "").upper(), None)
        return {
            "external_id": raw.get("reviewId") or raw.get("name"),
            "testo": comment.get("comment", ""),
            "valutazione_stelle": star,
            "fonte": "google",
            "autore": reviewer.get("displayName", ""),
        }

    async def fetch_reviews(self, org_id, page_size=50):
        """Recupera e persiste le review Google dell'org (con dedup).

        Ritorna il numero di review nuove inserite (0 se non connessi o se
        account/location non ancora configurati).
        """
        async with self.repo.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT account_name, location_name FROM {REVIEWS_TABLE} WHERE organization_id = $1",
                org_id,
            )
        if not row or not row["account_name"] or not row["location_name"]:
            logger.warning("business=sync_missing_ids org_id=%s", org_id)
            return 0

        service = await self._build_service(org_id)
        if service is None:
            return 0

        raw_reviews = await self._list_reviews(
            service, row["account_name"], row["location_name"], page_size=page_size
        )
        nuove = 0
        import asyncpg
        from src.core.crew_runner_review import genera_risposta_recensione
        for raw in raw_reviews:
            m = self._map_review(raw)
            if not m["testo"]:
                continue
            try:
                output = await asyncio.to_thread(
                    genera_risposta_recensione,
                    testo=m["testo"],
                    stelle=m["valutazione_stelle"],
                    autore=m["autore"],
                )
                await self.repo.create_review(
                    organization_id=org_id,
                    testo=m["testo"],
                    valutazione_stelle=m["valutazione_stelle"],
                    fonte="google",
                    autore=m["autore"],
                    external_id=m["external_id"],
                    bozza_risposta=output.bozza_risposta,
                    sentiment=output.sentiment,
                    categoria=output.categoria,
                    richiede_revisione_urgente=output.richiede_revisione_urgente,
                    stato="bozza_generata",
                )
                nuove += 1
            except asyncpg.UniqueViolationError:
                # Dedup: la review con questo external_id esiste gia' per
                # l'org (partial unique index), il sync e' idempotente.
                continue
            except Exception as e:
                logger.error("business=review_persist_fail org_id=%s ext=%s err=%s",
                             org_id, m["external_id"], e)
        async with self.repo.pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {REVIEWS_TABLE} SET last_sync_at = NOW() WHERE organization_id = $1",
                org_id,
            )
        return nuove
