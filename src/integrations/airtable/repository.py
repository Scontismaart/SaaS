"""Repository per la gestione delle connessioni Airtable a livello di tenant (Invarianti 1, 2, 10).

Salva le credenziali cifrate a riposo con Fernet (envelope simmetrico)
nella tabella airtable_connections, garantendo isolamento multi-tenant
tramite TenantScopedRepository e conformità AST di CI.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from cryptography.fernet import Fernet

from src.core.db.scoping import TenantScopedRepository, system_scope
from src.integrations.airtable.models import (
    AirtableWebhookEvent,
    AirtableWebhookSubscription,
    TableFieldMapping,
)

logger = logging.getLogger(__name__)


class AirtableConnectionRepository(TenantScopedRepository):
    """Repository tenant-scoped per la gestione delle connessioni Airtable."""

    def __init__(self, pool):
        self.pool = pool

    # ── Crittografia a Riposo (Invariante 10) ─────────────────────────────────

    @classmethod
    def _get_fernet(cls) -> Fernet:
        key = os.environ.get("ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "ENCRYPTION_KEY mancante: richiesta per la cifratura delle credenziali Airtable."
            )
        return Fernet(key.encode() if isinstance(key, str) else key)

    @classmethod
    def encrypt_credentials(cls, credentials: dict[str, Any]) -> str:
        """Cifra un envelope di credenziali (dict) in formato stringa Fernet."""
        json_str = json.dumps(credentials or {})
        return cls._get_fernet().encrypt(json_str.encode()).decode()

    @classmethod
    def decrypt_credentials(cls, ciphertext: str) -> dict[str, Any]:
        """Decifra un blob Fernet e restituisce il dizionario delle credenziali."""
        if not ciphertext:
            return {}
        try:
            decrypted = cls._get_fernet().decrypt(ciphertext.encode()).decode()
            return json.loads(decrypted)
        except Exception as exc:
            logger.error("airtable_credentials_decryption_failed: %s", exc)
            return {}

    # ── Operazioni sulle Connessioni (Tenant-Scoped) ──────────────────────────

    async def save_connection(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        token: str,
        token_type: str = "pat",
        base_name: str = "",
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """Salva o aggiorna una connessione Airtable cifrando il token a riposo."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        clean_token = token.strip()
        clean_base = base_id.strip()
        scopes_list = scopes or []
        meta_dict = metadata or {}

        envelope = {
            "token": clean_token,
            "token_type": token_type,
        }
        encrypted = self.encrypt_credentials(envelope)

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO airtable_connections (
                    id, organization_id, token_type, credentials_encrypted,
                    base_id, base_name, scopes, metadata, is_active,
                    created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
                ON CONFLICT (organization_id, base_id) DO UPDATE SET
                    token_type = EXCLUDED.token_type,
                    credentials_encrypted = EXCLUDED.credentials_encrypted,
                    base_name = EXCLUDED.base_name,
                    scopes = EXCLUDED.scopes,
                    metadata = EXCLUDED.metadata,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
                RETURNING id, organization_id, token_type, base_id, base_name, scopes, is_active, created_at, updated_at
                """,
                uuid.uuid4(),
                organization_id,
                token_type,
                encrypted,
                clean_base,
                base_name,
                scopes_list,
                json.dumps(meta_dict),
                is_active,
            )
            return dict(row) if row else {}

    async def get_connection(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
    ) -> dict[str, Any] | None:
        """Recupera la connessione includendo il token decifrato (uso strettamente interno)."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, token_type, credentials_encrypted,
                       base_id, base_name, scopes, metadata, is_active,
                       created_at, updated_at
                FROM airtable_connections
                WHERE organization_id = $1 AND base_id = $2
                """,
                organization_id,
                base_id.strip(),
            )
            if not row:
                return None

            data = dict(row)
            enc = data.pop("credentials_encrypted", "")
            creds = self.decrypt_credentials(enc)
            data["token"] = creds.get("token", "")
            return data

    async def get_default_active_connection(
        self,
        organization_id: uuid.UUID | str,
    ) -> dict[str, Any] | None:
        """Recupera la prima connessione attiva per il tenant con token decifrato per uso interno."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, token_type, credentials_encrypted,
                       base_id, base_name, scopes, metadata, is_active,
                       created_at, updated_at
                FROM airtable_connections
                WHERE organization_id = $1 AND is_active = TRUE
                ORDER BY created_at DESC LIMIT 1
                """,
                organization_id,
            )
            if not row:
                return None

            data = dict(row)
            enc = data.pop("credentials_encrypted", "")
            creds = self.decrypt_credentials(enc)
            data["token"] = creds.get("token", "")
            return data

    async def list_connections(
        self,
        organization_id: uuid.UUID | str,
        only_active: bool = True,
    ) -> list[dict[str, Any]]:
        """Restituisce l'elenco delle connessioni per il tenant (senza token in chiaro - Invariante 10)."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        query = """
            SELECT id, organization_id, token_type, base_id, base_name,
                   scopes, is_active, created_at, updated_at
            FROM airtable_connections
            WHERE organization_id = $1
        """
        if only_active:
            query += " AND is_active = TRUE"
        query += " ORDER BY created_at DESC"

        async with self.scoped_conn(organization_id) as conn:
            rows = await conn.fetch(query, organization_id)
            return [dict(r) for r in rows]

    async def disconnect(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
    ) -> bool:
        """Disconnette e rimuove la connessione Airtable per la Base indicata."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            res = await conn.execute(
                """
                DELETE FROM airtable_connections
                WHERE organization_id = $1 AND base_id = $2
                """,
                organization_id,
                base_id.strip(),
            )
            return "DELETE 1" in res or res == "DELETE 1"

    async def set_active(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        is_active: bool,
    ) -> bool:
        """Attiva o sospende una connessione Airtable."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            res = await conn.execute(
                """
                UPDATE airtable_connections
                SET is_active = $1, updated_at = NOW()
                WHERE organization_id = $2 AND base_id = $3
                """,
                is_active,
                organization_id,
                base_id.strip(),
            )
            return "UPDATE 1" in res or res == "UPDATE 1"


class AirtableMappingRepository(TenantScopedRepository):
    """Repository tenant-scoped per la persistenza dei mapping tra modello interno e tabelle Airtable."""

    def __init__(self, pool):
        self.pool = pool

    async def save_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str,
        field_mappings: dict[str, str],
        required_fields: list[str] | None = None,
        is_active: bool = True,
    ) -> TableFieldMapping:
        """Salva o aggiorna la configurazione di mapping per un'entità su una tabella Airtable."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        clean_base = base_id.strip()
        clean_table = table_id_or_name.strip()
        clean_entity = entity_type.strip().lower()
        req_list = required_fields or []
        mapping_json = json.dumps(field_mappings or {})

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO airtable_field_mappings (
                    id, organization_id, base_id, table_id_or_name, entity_type,
                    field_mappings, required_fields, is_active, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, NOW(), NOW())
                ON CONFLICT (organization_id, base_id, table_id_or_name, entity_type) DO UPDATE SET
                    field_mappings = EXCLUDED.field_mappings,
                    required_fields = EXCLUDED.required_fields,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
                RETURNING id, organization_id, base_id, table_id_or_name, entity_type,
                          field_mappings, required_fields, is_active, created_at, updated_at
                """,
                uuid.uuid4(),
                organization_id,
                clean_base,
                clean_table,
                clean_entity,
                mapping_json,
                req_list,
                is_active,
            )
            data = dict(row)
            if isinstance(data.get("field_mappings"), str):
                data["field_mappings"] = json.loads(data["field_mappings"])
            return TableFieldMapping(**data)

    async def get_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str,
    ) -> TableFieldMapping | None:
        """Recupera la configurazione di mapping per la specifica tabella ed entità del tenant."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, base_id, table_id_or_name, entity_type,
                       field_mappings, required_fields, is_active, created_at, updated_at
                FROM airtable_field_mappings
                WHERE organization_id = $1 AND base_id = $2 AND table_id_or_name = $3 AND entity_type = $4
                """,
                organization_id,
                base_id.strip(),
                table_id_or_name.strip(),
                entity_type.strip().lower(),
            )
            if not row:
                return None
            data = dict(row)
            if isinstance(data.get("field_mappings"), str):
                data["field_mappings"] = json.loads(data["field_mappings"])
            return TableFieldMapping(**data)

    async def list_mappings(
        self,
        organization_id: uuid.UUID | str,
        base_id: str | None = None,
        only_active: bool = True,
    ) -> list[TableFieldMapping]:
        """Elenca tutti i mapping configurati per il tenant, opzionalmente filtrati per Base."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        params: list[Any] = [organization_id]
        query = """
            SELECT id, organization_id, base_id, table_id_or_name, entity_type,
                   field_mappings, required_fields, is_active, created_at, updated_at
            FROM airtable_field_mappings
            WHERE organization_id = $1
        """
        if base_id:
            params.append(base_id.strip())
            query += f" AND base_id = ${len(params)}"
        if only_active:
            query += " AND is_active = TRUE"
        query += " ORDER BY created_at ASC"

        async with self.scoped_conn(organization_id) as conn:
            rows = await conn.fetch(query, *params)
            results = []
            for r in rows:
                data = dict(r)
                if isinstance(data.get("field_mappings"), str):
                    data["field_mappings"] = json.loads(data["field_mappings"])
                results.append(TableFieldMapping(**data))
            return results

    async def delete_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str,
    ) -> bool:
        """Elimina il mapping specificato per il tenant."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            res = await conn.execute(
                """
                DELETE FROM airtable_field_mappings
                WHERE organization_id = $1 AND base_id = $2 AND table_id_or_name = $3 AND entity_type = $4
                """,
                organization_id,
                base_id.strip(),
                table_id_or_name.strip(),
                entity_type.strip().lower(),
            )
            return "DELETE 1" in res or res == "DELETE 1"

    async def get_mapping_by_entity(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        entity_type: str,
    ) -> TableFieldMapping | None:
        """Recupera la prima configurazione di mapping attiva per una determinata entità del tenant."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, base_id, table_id_or_name, entity_type,
                       field_mappings, required_fields, is_active, created_at, updated_at
                FROM airtable_field_mappings
                WHERE organization_id = $1 AND base_id = $2 AND entity_type = $3 AND is_active = TRUE
                ORDER BY created_at ASC LIMIT 1
                """,
                organization_id,
                base_id.strip(),
                entity_type.strip().lower(),
            )
            if not row:
                return None
            data = dict(row)
            if isinstance(data.get("field_mappings"), str):
                data["field_mappings"] = json.loads(data["field_mappings"])
            return TableFieldMapping(**data)

    async def get_mapping_by_table(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
    ) -> TableFieldMapping | None:
        """Recupera la prima configurazione di mapping attiva per una determinata tabella del tenant."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, base_id, table_id_or_name, entity_type,
                       field_mappings, required_fields, is_active, created_at, updated_at
                FROM airtable_field_mappings
                WHERE organization_id = $1 AND base_id = $2 AND table_id_or_name = $3 AND is_active = TRUE
                ORDER BY created_at ASC LIMIT 1
                """,
                organization_id,
                base_id.strip(),
                table_id_or_name.strip(),
            )
            if not row:
                return None
            data = dict(row)
            if isinstance(data.get("field_mappings"), str):
                data["field_mappings"] = json.loads(data["field_mappings"])
            return TableFieldMapping(**data)



class AirtableWebhookRepository(TenantScopedRepository):
    """Repository tenant-scoped per le sottoscrizioni webhook e la persistenza idempotente degli eventi Airtable."""

    def __init__(self, pool):
        self.pool = pool

    @classmethod
    def _get_fernet(cls) -> Fernet:
        key = os.environ.get("ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "ENCRYPTION_KEY mancante: richiesta per la cifratura del segreto webhook Airtable."
            )
        return Fernet(key.encode() if isinstance(key, str) else key)

    @classmethod
    def encrypt_secret(cls, secret: str) -> str:
        """Cifra il segreto MAC del webhook a riposo."""
        return cls._get_fernet().encrypt(secret.encode()).decode()

    @classmethod
    def decrypt_secret(cls, ciphertext: str) -> str:
        """Decifra il segreto MAC del webhook."""
        if not ciphertext:
            return ""
        try:
            return cls._get_fernet().decrypt(ciphertext.encode()).decode()
        except Exception as exc:
            logger.error("airtable_webhook_secret_decryption_failed: %s", exc)
            return ""

    async def save_subscription(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        webhook_id: str,
        mac_secret: str,
        cursor: int = 1,
        notification_url: str = "",
        specification: dict[str, Any] | None = None,
        is_active: bool = True,
    ) -> AirtableWebhookSubscription:
        """Salva o aggiorna una sottoscrizione webhook cifrando il segreto MAC a riposo."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        encrypted_mac = self.encrypt_secret(mac_secret.strip())
        spec_json = json.dumps(specification or {})

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO airtable_webhooks (
                    id, organization_id, base_id, webhook_id, mac_secret_encrypted,
                    cursor, notification_url, specification, is_active,
                    created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, NOW(), NOW())
                ON CONFLICT (webhook_id) DO UPDATE SET
                    mac_secret_encrypted = EXCLUDED.mac_secret_encrypted,
                    cursor = EXCLUDED.cursor,
                    notification_url = EXCLUDED.notification_url,
                    specification = EXCLUDED.specification,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
                RETURNING id, organization_id, base_id, webhook_id, mac_secret_encrypted,
                          cursor, notification_url, specification, is_active, created_at, updated_at
                """,
                uuid.uuid4(),
                organization_id,
                base_id.strip(),
                webhook_id.strip(),
                encrypted_mac,
                cursor,
                notification_url.strip(),
                spec_json,
                is_active,
            )
            data = dict(row)
            enc = data.pop("mac_secret_encrypted", "")
            data["mac_secret"] = self.decrypt_secret(enc)
            if isinstance(data.get("specification"), str):
                data["specification"] = json.loads(data["specification"])
            return AirtableWebhookSubscription(**data)

    async def get_subscription_by_webhook_id(
        self,
        webhook_id: str,
    ) -> AirtableWebhookSubscription | None:
        """Risoluzione sicura dell'integrazione: identifica tenant e segreto MAC dal webhook_id univoco."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, base_id, webhook_id, mac_secret_encrypted,
                       cursor, notification_url, specification, is_active, created_at, updated_at
                FROM airtable_webhooks
                WHERE webhook_id = $1
                """,
                webhook_id.strip(),
            )
            if not row:
                return None
            data = dict(row)
            enc = data.pop("mac_secret_encrypted", "")
            data["mac_secret"] = self.decrypt_secret(enc)
            if isinstance(data.get("specification"), str):
                data["specification"] = json.loads(data["specification"])
            return AirtableWebhookSubscription(**data)

    async def get_subscription(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
    ) -> AirtableWebhookSubscription | None:
        """Recupera la sottoscrizione webhook per una Base del tenant."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, base_id, webhook_id, mac_secret_encrypted,
                       cursor, notification_url, specification, is_active, created_at, updated_at
                FROM airtable_webhooks
                WHERE organization_id = $1 AND base_id = $2
                """,
                organization_id,
                base_id.strip(),
            )
            if not row:
                return None
            data = dict(row)
            enc = data.pop("mac_secret_encrypted", "")
            data["mac_secret"] = self.decrypt_secret(enc)
            if isinstance(data.get("specification"), str):
                data["specification"] = json.loads(data["specification"])
            return AirtableWebhookSubscription(**data)

    async def record_event_idempotent(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        webhook_id: str,
        external_event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> tuple[AirtableWebhookEvent | None, bool]:
        """Salva l'evento webhook garantendo idempotenza atomica.

        Restituisce (event, is_duplicate).
        """
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        payload_json = json.dumps(payload or {})

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO airtable_webhook_events (
                    id, organization_id, base_id, webhook_id, external_event_id,
                    event_type, payload, status, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, 'pending', NOW())
                ON CONFLICT (organization_id, webhook_id, external_event_id) DO NOTHING
                RETURNING id, organization_id, base_id, webhook_id, external_event_id,
                          event_type, payload, status, error_message, created_at, processed_at
                """,
                uuid.uuid4(),
                organization_id,
                base_id.strip(),
                webhook_id.strip(),
                external_event_id.strip(),
                event_type.strip(),
                payload_json,
            )
            if row:
                data = dict(row)
                if isinstance(data.get("payload"), str):
                    data["payload"] = json.loads(data["payload"])
                return AirtableWebhookEvent(**data), False

            existing_row = await conn.fetchrow(
                """
                SELECT id, organization_id, base_id, webhook_id, external_event_id,
                       event_type, payload, status, error_message, created_at, processed_at
                FROM airtable_webhook_events
                WHERE organization_id = $1 AND webhook_id = $2 AND external_event_id = $3
                """,
                organization_id,
                webhook_id.strip(),
                external_event_id.strip(),
            )
            if existing_row:
                data = dict(existing_row)
                if isinstance(data.get("payload"), str):
                    data["payload"] = json.loads(data["payload"])
                return AirtableWebhookEvent(**data), True
            return None, True

    async def update_cursor(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        cursor: int,
    ) -> bool:
        """Avanza il cursore di lettura dei payload webhook per la Base del tenant.

        Stato interno del modello thin-ping Airtable: il cursore indica il prossimo
        cursore da richiedere a `GET /v0/bases/{baseId}/webhooks/{webhookId}/payloads`.
        Guardia monotonica DB-side: uno writer stale (cursore letto prima di un
        avanzamento concorrente) non regredisce mai il cursore. Ritorna True solo
        se l'avanzamento e' stato applicato.
        """
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        async with self.scoped_conn(organization_id) as conn:
            res = await conn.execute(
                """
                UPDATE airtable_webhooks
                SET cursor = $1, updated_at = NOW()
                WHERE organization_id = $2 AND base_id = $3 AND cursor < $1
                """,
                int(cursor),
                organization_id,
                base_id.strip(),
            )
            return "UPDATE 1" in res or res == "UPDATE 1"

    async def update_event_status(
        self,
        organization_id: uuid.UUID | str,
        event_id: uuid.UUID | str,
        status: str,
        error_message: str | None = None,
    ) -> bool:
        """Aggiorna lo stato di elaborazione dell'evento webhook."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        if isinstance(event_id, str):
            event_id = uuid.UUID(event_id)

        async with self.scoped_conn(organization_id) as conn:
            res = await conn.execute(
                """
                UPDATE airtable_webhook_events
                SET status = $1, error_message = $2, processed_at = NOW()
                WHERE id = $3 AND organization_id = $4
                """,
                status,
                error_message,
                event_id,
                organization_id,
            )
            return "UPDATE 1" in res or res == "UPDATE 1"

    async def claim_event_processing(
        self,
        organization_id: uuid.UUID | str,
        event_id: uuid.UUID | str,
    ) -> bool:
        """Claim atomico dell'elaborazione: un solo worker per evento.

        Transizione consentita solo da 'pending' -> 'processing'. Ritorna True
        solo per il vincitore; gli altri rileggono lo stato (terminale -> skip,
        processing -> deferred) invece di elaborare due volte.
        """
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        if isinstance(event_id, str):
            event_id = uuid.UUID(event_id)

        async with self.scoped_conn(organization_id) as conn:
            res = await conn.execute(
                """
                UPDATE airtable_webhook_events
                SET status = 'processing', processed_at = NOW()
                WHERE id = $1 AND organization_id = $2 AND status = 'pending'
                """,
                event_id,
                organization_id,
            )
            return "UPDATE 1" in res or res == "UPDATE 1"

    async def get_event(
        self,
        organization_id: uuid.UUID | str,
        event_id: uuid.UUID | str,
    ) -> AirtableWebhookEvent | None:
        """Recupera un evento webhook per tenant e id."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        if isinstance(event_id, str):
            event_id = uuid.UUID(event_id)

        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, base_id, webhook_id, external_event_id,
                       event_type, payload, status, error_message, created_at, processed_at
                FROM airtable_webhook_events
                WHERE id = $1 AND organization_id = $2
                """,
                event_id,
                organization_id,
            )
            if not row:
                return None
            data = dict(row)
            if isinstance(data.get("payload"), str):
                data["payload"] = json.loads(data["payload"])
            return AirtableWebhookEvent(**data)

    async def list_events(
        self,
        organization_id: uuid.UUID | str,
        base_id: str | None = None,
        limit: int = 50,
    ) -> list[AirtableWebhookEvent]:
        """Elenca gli eventi webhook per il tenant specificato."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        query = """
            SELECT id, organization_id, base_id, webhook_id, external_event_id,
                   event_type, payload, status, error_message, created_at, processed_at
            FROM airtable_webhook_events
            WHERE organization_id = $1
        """
        params: list[Any] = [organization_id]
        if base_id:
            query += " AND base_id = $2"
            params.append(base_id.strip())
        query += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)

        async with self.scoped_conn(organization_id) as conn:
            rows = await conn.fetch(query, *params)
            events = []
            for r in rows:
                data = dict(r)
                if isinstance(data.get("payload"), str):
                    data["payload"] = json.loads(data["payload"])
                events.append(AirtableWebhookEvent(**data))
            return events

    @system_scope("worker queue: recupera eventi webhook Airtable orfani in processing")
    async def reap_stale_processing(
        self, older_than_seconds: int = 1800, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Riporta a 'pending' gli eventi bloccati in 'processing' oltre soglia.

        Un evento resta in 'processing' solo se il worker e' crashato tra claim
        e mark: senza reaper resterebbe orfano per sempre. Usa created_at
        (nessuna migration necessaria). Idempotente e cross-tenant by design
        (solo job fidati).
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE airtable_webhook_events
                SET status = 'pending',
                    error_message = 'reaped: processing oltre soglia, rimesso in coda',
                    processed_at = NOW()
                WHERE status = 'processing'
                  AND created_at < NOW() - make_interval(secs => $1)
                ORDER BY created_at ASC
                LIMIT $2
                RETURNING id, organization_id, base_id, webhook_id, external_event_id
                """,
                int(older_than_seconds),
                int(limit),
            )
            return [dict(r) for r in rows]
