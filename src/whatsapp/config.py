import logging
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    app_secret: str
    encryption_key: str
    postgres_dsn: str
    verify_token: str
    max_retry_attempts: int = 5


@dataclass
class TenantConfig:
    organization_id: UUID
    phone_number_id: str
    waba_id: str
    access_token: str
    timezone: str = "Europe/Rome"
    business_profile: dict = field(default_factory=dict)


async def load_tenant_config(org_id: UUID, app_config: AppConfig, repo) -> TenantConfig:
    from cryptography.fernet import Fernet, InvalidToken
    row = await repo.get_tenant_config(org_id)
    try:
        cipher = Fernet(app_config.encryption_key.encode())
        decrypted = cipher.decrypt(row["access_token"].encode()).decode()
    except InvalidToken:
        logger.error("INVALID_TOKEN: encryption_key may have been rotated. org_id=%s", org_id)
        raise
    return TenantConfig(
        organization_id=org_id,
        phone_number_id=row["phone_number_id"],
        waba_id=row["waba_id"],
        access_token=decrypted,
        timezone=row.get("timezone", "Europe/Rome"),
        business_profile=row.get("business_profile", {}),
    )
