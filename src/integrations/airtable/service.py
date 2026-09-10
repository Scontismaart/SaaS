"""Servizio per la gestione dell'autenticazione e del ciclo di vita delle connessioni Airtable.

Conforme a:
- Invariante 1 (Tenant Isolation): Eredita e valida organization_id.
- Invariante 5 (No Direct Privileged Actions): Isola le chiamate applicative da quelle AI.
- Invariante 9 (Osservabilità & Audit Log): Traccia connessioni e disconnessioni.
- Invariante 10 (Sicurezza Segreti): Cifra a riposo e non espone mai i token in chiaro.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from src.core.auth.audit import audit_log
from src.integrations.airtable.adapter import (
    AirtableAdapter,
    get_shared_rate_limiter,
    get_shared_schema_cache,
)
from src.integrations.airtable.errors import (
    AirtableAuthError,
    AirtableError,
    AirtableMedicalPolicyError,
    AirtableNotFoundError,
)
from src.integrations.airtable.models import SchemaValidationResult
from src.integrations.airtable.port import AirtablePort
from src.integrations.airtable.repository import AirtableConnectionRepository

logger = logging.getLogger(__name__)

# Verticali sensibili soggetti a divieto assoluto GDPR Art. 9 (dati sanitari particolari / clinici)
# NOTA DI MANUTENZIONE: Questo insieme deve essere allineato ogni volta che viene introdotto
# un nuovo verticale clinico, sanitario o parasanitario (es. psicologo, veterinario, ecc.).
MEDICAL_SENSITIVE_VERTICALS = frozenset({
    "studio_medico",
    "studio_medico_dentista",
    "medico",
    "clinica",
    "sanitario",
    "sanita",
    "odontoiatra",
    "dentista",
    "fisioterapia",
    "dottore",
    "poliambulatorio",
    "psicologo",
    "psicoterapeuta",
    "veterinario",
})


def is_medical_vertical(verticale: str | None) -> bool:
    """Verifica se il verticale appartiene al settore sanitario/clinico."""
    if not verticale:
        return False
    clean = str(verticale).strip().lower()
    if clean in MEDICAL_SENSITIVE_VERTICALS:
        return True
    parts = clean.replace("-", "_").split("_")
    return any(p in MEDICAL_SENSITIVE_VERTICALS for p in parts)


class AirtableConnectionService:
    """Service applicativo per authentication e connection management di Airtable."""

    def __init__(
        self,
        repo: AirtableConnectionRepository,
        core_repo: Any | None = None,
    ):
        self.repo = repo
        self.core_repo = core_repo

    async def _resolve_org_vertical(self, organization_id: uuid.UUID | str) -> str | None:
        """Risolve il verticale dell'organizzazione dal database/repository core."""
        if not self.core_repo:
            return None

        # 1. Tentativo da onboarding_profiles
        if hasattr(self.core_repo, "get_onboarding_profile"):
            try:
                prof = await self.core_repo.get_onboarding_profile(organization_id)
                if prof and prof.get("verticale"):
                    return str(prof["verticale"])
            except Exception as e:
                logger.debug("Impossibile leggere onboarding profile per org %s: %s", organization_id, e)

        # 2. Tentativo da business_profile
        fetch_bp = getattr(self.core_repo, "get_org_business_profile", None)
        if callable(fetch_bp):
            try:
                bp = await fetch_bp(organization_id) or {}
                if bp.get("verticale"):
                    return str(bp["verticale"])
            except Exception as e:
                logger.debug("Impossibile leggere business profile per org %s: %s", organization_id, e)

        # 3. Tentativo da get_organization
        fetch_org = getattr(self.core_repo, "get_organization", None)
        if callable(fetch_org):
            try:
                org_data = await fetch_org(organization_id) or {}
                bp = org_data.get("business_profile") or {}
                if isinstance(bp, dict) and bp.get("verticale"):
                    return str(bp["verticale"])
            except Exception as e:
                logger.debug("Impossibile leggere organization per org %s: %s", organization_id, e)

        return None

    async def connect_pat(
        self,
        organization_id: uuid.UUID | str,
        token: str,
        base_id: str,
        base_name: str = "",
        user_id: str | None = None,
        auth_user_id: str | None = None,
        verticale: str | None = None,
    ) -> dict[str, Any]:
        """Verifica e connette un Personal Access Token (PAT) per una Base Airtable.

        Esegue due livelli di validazione bloccante prima del salvataggio:
        1. Divieto Assoluto Settore Medico (GDPR Art. 9 & Invariante 6): Se l'organizzazione
           appartiene al settore medico/sanitario (es. studio_medico), la connessione è
           TASSATIVAMENTE VIETATA per prevenire la dispersione di dati clinici verso terzi.
        2. Validazione preventiva del token e della Base via Metadata API Airtable:
           se il token è invalido (401/403) o la Base inesistente (404),
           il salvataggio viene bloccato a monte (fail-closed).
        """
        clean_token = (token or "").strip()
        clean_base = (base_id or "").strip()

        if not clean_token:
            raise AirtableAuthError("Il Personal Access Token (PAT) di Airtable non può essere vuoto.")
        if not clean_base:
            raise AirtableError("Il Base ID di Airtable non può essere vuoto (es. 'appXXXXXXXXXXXXXX').")

        # 1. Divieto Totale Settore Medico / Sanitario (GDPR Art. 9)
        resolved_verticale = verticale

        if resolved_verticale is None and self.core_repo:
            resolved_verticale = await self._resolve_org_vertical(organization_id)

        if is_medical_vertical(resolved_verticale):
            logger.warning(
                "airtable_connect_prohibited reason=medical_vertical_total_prohibition org_id=%s verticale=%s",
                organization_id,
                resolved_verticale,
            )
            raise AirtableMedicalPolicyError(
                f"Connessione ad Airtable non consentita per il settore medico/sanitario ('{resolved_verticale}'). "
                "Airtable non è autorizzato per la gestione o archiviazione di dati sanitari o clinici (GDPR Art. 9). "
                "L'integrazione è tassativamente interdetta per policy di conformità e sicurezza."
            )

        # 2. Verifica live del token e dello scope interrogando la Metadata API
        # Resilienza: rate limiter 5 req/s per base e cache metadata condivisi a livello di processo.
        temp_adapter = AirtableAdapter(
            token=clean_token,
            rate_limiter=get_shared_rate_limiter(),
            schema_cache=get_shared_schema_cache(),
        )
        try:
            tables = await temp_adapter.get_base_schema(clean_base)
            detected_tables_count = len(tables)
        except AirtableAuthError as exc:
            logger.warning("airtable_connect_failed reason=auth_failed org_id=%s: %s", organization_id, exc)
            raise
        except AirtableNotFoundError as exc:
            logger.warning("airtable_connect_failed reason=base_not_found org_id=%s base_id=%s: %s", organization_id, clean_base, exc)
            raise

        detected_scopes = ["data.records:read", "data.records:write", "schema.bases:read"]
        metadata = {
            "tables_count": detected_tables_count,
            "connected_via": "pat",
            "verticale": resolved_verticale,
            "medical_prohibition_check": "passed",
        }

        saved = await self.repo.save_connection(
            organization_id=organization_id,
            base_id=clean_base,
            token=clean_token,
            token_type="pat",
            base_name=base_name or clean_base,
            scopes=detected_scopes,
            metadata=metadata,
            is_active=True,
        )

        # Tracciamento in audit log
        if self.core_repo:
            try:
                await audit_log(
                    repo=self.core_repo,
                    organization_id=str(organization_id),
                    action="integration.airtable.connected",
                    user_id=user_id,
                    auth_user_id=auth_user_id,
                    target_table="airtable_connections",
                    target_id=str(saved.get("id", "")),
                    details={
                        "base_id": clean_base,
                        "base_name": saved.get("base_name"),
                        "token_type": "pat",
                    },
                )
            except Exception as e:
                logger.warning("audit_log failed for airtable connection: %s", e)

        # Invariante 10: Ritorna esclusivamente metadati sanificati, MAI il token
        return {
            "success": True,
            "message": f"Connessione ad Airtable verificata con successo per la Base '{saved.get('base_name')}'.",
            "connection_id": str(saved.get("id")),
            "organization_id": str(organization_id),
            "base_id": clean_base,
            "base_name": saved.get("base_name"),
            "token_type": "pat",
            "is_active": saved.get("is_active", True),
            "tables_count": detected_tables_count,
            "verticale": resolved_verticale,
            "updated_at": saved.get("updated_at"),
        }

    async def get_adapter_for_tenant(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
    ) -> AirtablePort:
        """Costruisce e restituisce un AirtableAdapter pronto all'uso con credenziali decifrate."""
        conn = await self.repo.get_connection(organization_id, base_id)
        if not conn or not conn.get("is_active", True):
            raise AirtableNotFoundError(
                f"Nessuna connessione Airtable attiva trovata per l'organizzazione {organization_id} e Base {base_id}."
            )

        token = conn.get("token")
        if not token:
            raise AirtableAuthError("Credenziali Airtable non disponibili o corrotte a riposo.")

        # Resilienza: rate limiter 5 req/s per base e cache metadata condivisi a livello di processo.
        return AirtableAdapter(
            token=token,
            rate_limiter=get_shared_rate_limiter(),
            schema_cache=get_shared_schema_cache(),
        )

    async def validate_schema_for_tenant(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        required_fields: list[str],
    ) -> SchemaValidationResult:
        """Gate bloccante: valida lo schema di una tabella prima di salvare configurazioni o mapping."""
        adapter = await self.get_adapter_for_tenant(organization_id, base_id)
        return await adapter.validate_table_schema(base_id, table_id_or_name, required_fields)

    async def disconnect(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        user_id: str | None = None,
        auth_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Disconnette e rimuove la connessione Airtable."""
        deleted = await self.repo.disconnect(organization_id, base_id)
        if deleted and self.core_repo:
            try:
                await audit_log(
                    repo=self.core_repo,
                    organization_id=str(organization_id),
                    action="integration.airtable.disconnected",
                    user_id=user_id,
                    auth_user_id=auth_user_id,
                    target_table="airtable_connections",
                    details={"base_id": base_id},
                )
            except Exception as e:
                logger.warning("audit_log failed for airtable disconnection: %s", e)

        return {
            "success": deleted,
            "message": "Connessione Airtable rimossa con successo." if deleted else "Nessuna connessione trovata da rimuovere.",
            "base_id": base_id,
        }

    async def get_status(
        self,
        organization_id: uuid.UUID | str,
    ) -> dict[str, Any]:
        """Restituisce lo stato complessivo delle connessioni Airtable per il tenant (senza token in chiaro)."""
        connections = await self.repo.list_connections(organization_id, only_active=False)
        return {
            "is_configured": len(connections) > 0,
            "active_connections_count": sum(1 for c in connections if c.get("is_active")),
            "connections": [
                {
                    "id": str(c["id"]),
                    "base_id": c["base_id"],
                    "base_name": c["base_name"],
                    "token_type": c["token_type"],
                    "is_active": c["is_active"],
                    "verticale": c.get("metadata", {}).get("verticale") if isinstance(c.get("metadata"), dict) else None,
                    "updated_at": c["updated_at"].isoformat() if hasattr(c["updated_at"], "isoformat") else str(c["updated_at"]),
                }
                for c in connections
            ],
        }

