import json
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.db.repository import CoreRepository


async def audit_log(
    repo: "CoreRepository",
    organization_id: str,
    action: str,
    user_id: str | None = None,
    auth_user_id: str | None = None,
    target_table: str | None = None,
    target_id: str | None = None,
    details: dict | None = None,
) -> dict:
    async with repo.pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO audit_log (id, organization_id, user_id, auth_user_id,
                                   action, target_table, target_id, details)
            VALUES ($1, $2::uuid, $3::uuid, $4, $5, $6, $7::uuid, $8::jsonb)
            RETURNING *
        """, uuid.uuid4(), organization_id, user_id, auth_user_id,
           action, target_table, target_id,
           json.dumps(details or {}))
        return dict(row)
