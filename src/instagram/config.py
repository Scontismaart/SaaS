import logging
from dataclasses import dataclass
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class InstagramTenantConfig:
    organization_id: UUID
    ig_user_id: str
    access_token: str


async def load_instagram_config(org_id: UUID, encryption_key: str, igrepo) -> InstagramTenantConfig | None:
    """Carica e decripta le credenziali Instagram dell'org. None se l'org
    non ha un account Instagram collegato (canale non attivo)."""
    from cryptography.fernet import Fernet, InvalidToken
    row = await igrepo.get_instagram_account(org_id)
    if not row:
        return None
    try:
        cipher = Fernet(encryption_key.encode())
        decrypted = cipher.decrypt(row["access_token"].encode()).decode()
    except InvalidToken:
        logger.error(
            "INVALID_TOKEN instagram: encryption_key may have been rotated. org_id=%s", org_id
        )
        raise
    return InstagramTenantConfig(
        organization_id=org_id,
        ig_user_id=row["ig_user_id"],
        access_token=decrypted,
    )
