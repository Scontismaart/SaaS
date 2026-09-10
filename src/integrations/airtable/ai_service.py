"""Application Service per l'esecuzione sicura di capability CRM su Airtable da parte dell'AI.

Conforme a:
- Invariante 1 (Tenant Isolation): Riceve organization_id dal contesto autenticato/sessione, mai dal modello LLM.
- Invariante 5 (No Direct Privileged Actions): Il modello esprime solo intenti e parametri di business;
  la validazione, il mapping, le policy e la chiamata alle API avvengono nel service applicativo.
- Invariante 6 (GDPR Compliance): Interdizione assoluta per organizzazioni del settore medico/sanitario (Art. 9).
- Permessi e Capability Limitate: Nessuna alterazione di schema (tabelle, campi o permessi Airtable).
- Write Safety: Le operazioni distruttive richiedono token di conferma esplicito; nessun delete ambiguo.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import uuid
from typing import Any, Callable

from src.integrations.airtable.errors import (
    AirtableAIError,
    AirtableConfirmationRequiredError,
    AirtableMedicalPolicyError,
    AirtableMissingFieldMappingError,
    AirtableNotFoundError,
    AirtableSchemaModificationProhibitedError,
    AirtableValidationError,
)
from src.integrations.airtable.models import (
    CreateRecordRequest,
    TableFieldMapping,
    UpdateRecordRequest,
)
from src.integrations.airtable.port import AirtablePort
from src.integrations.airtable.repository import (
    AirtableConnectionRepository,
    AirtableMappingRepository,
)
from src.integrations.airtable.service import is_medical_vertical

logger = logging.getLogger(__name__)

# Entità supportate e autorizzate per l'AI
ALLOWED_AI_ENTITIES = frozenset({"customer", "lead", "request", "ticket"})


def _compute_delete_confirmation_token(
    organization_id: uuid.UUID | str,
    entity_type: str,
    record_id: str,
) -> str:
    """Token di conferma per operazioni distruttive: HMAC-SHA256 legato a tenant+entità+record.

    Hardening Write Safety: il token NON è più prevedibile dal modello (il vecchio formato
    deterministico 'CONFIRM_DELETE_{record_id}' era fabbricabile dall'LLM senza passare
    dalla richiesta di conferma). Il segreto è server-side (ENCRYPTION_KEY, già richiesta
    per la cifratura delle credenziali): l'LLM deve ottenere il token dall'errore di
    conferma richiesto dal service, che lo presenta all'operatore umano.
    """
    secret = (os.environ.get("ENCRYPTION_KEY") or "").encode("utf-8")
    message = f"airtable-delete:{organization_id}:{entity_type}:{record_id}".encode("utf-8")
    digest = hmac.new(secret, message, hashlib.sha256).hexdigest()[:32]
    return f"CONFIRM_DELETE_{digest}"


def _verify_delete_confirmation_token(provided: str | None, expected: str) -> bool:
    """Confronto a tempo costante del token di conferma."""
    return hmac.compare_digest(str(provided or ""), expected)


def _escape_formula_str(value: str) -> str:
    """Sanitizza e neutralizza stringhe destinate a formule Airtable contro attacchi di formula injection."""
    if not value:
        return ""
    # Rimuove caratteri di escape pericolosi o apici che potrebbero rompere la formula
    clean = value.replace("\\", "\\\\").replace("'", "\\'")
    # Neutralizza newline
    clean = clean.replace("\r", " ").replace("\n", " ")
    return clean


class AirtableAIService:
    """Service applicativo che espone capability CRM sicure per l'agente AI."""

    def __init__(
        self,
        connection_repo: AirtableConnectionRepository | None = None,
        mapping_repo: AirtableMappingRepository | None = None,
        port: AirtablePort | None = None,
        port_factory: Callable[[str, str], AirtablePort] | None = None,
        core_repo: Any | None = None,
    ):
        self.connection_repo = connection_repo
        self.mapping_repo = mapping_repo
        self.port = port
        self.port_factory = port_factory
        self.core_repo = core_repo

    async def _resolve_org_vertical(self, organization_id: uuid.UUID | str) -> str | None:
        """Risolve il settore di appartenenza del tenant dal database core o metadata."""
        if not self.core_repo:
            return None
        # Onboarding profile
        if hasattr(self.core_repo, "get_onboarding_profile"):
            try:
                prof = await self.core_repo.get_onboarding_profile(organization_id)
                if prof and prof.get("verticale"):
                    return str(prof["verticale"])
            except Exception:
                pass
        # Business profile
        fetch_bp = getattr(self.core_repo, "get_org_business_profile", None)
        if callable(fetch_bp):
            try:
                bp = await fetch_bp(organization_id) or {}
                if bp.get("verticale"):
                    return str(bp["verticale"])
            except Exception:
                pass
        return None

    async def _check_tenant_and_vertical(self, organization_id: uuid.UUID | str) -> None:
        """Verifica preventiva di conformità: interdizione categorica per settore medico."""
        verticale = await self._resolve_org_vertical(organization_id)
        if is_medical_vertical(verticale):
            logger.warning(
                "Blocco capability AI Airtable per tenant %s: settore medico '%s' interdetto.",
                organization_id, verticale,
            )
            raise AirtableMedicalPolicyError(
                f"Capability AI su Airtable non consentite per il settore '{verticale}'. "
                "Airtable non è autorizzato al trattamento di dati sanitari (GDPR Art. 9)."
            )

    async def _resolve_port_and_base(
        self,
        organization_id: uuid.UUID | str,
        base_id: str | None = None,
    ) -> tuple[AirtablePort, str]:
        """Risolve l'adapter e il base_id attivo per il tenant. Zero secrets esposti all'AI."""
        await self._check_tenant_and_vertical(organization_id)

        # In modalità test con port pre-iniettato (es. FakeAirtablePort)
        if self.port is not None:
            resolved_base = base_id or "app_test_mock"
            return self.port, resolved_base

        if not self.connection_repo:
            raise AirtableNotFoundError("Repository delle connessioni non configurato.")

        if base_id:
            conn = await self.connection_repo.get_connection(organization_id, base_id)
        else:
            conn = await self.connection_repo.get_default_active_connection(organization_id)

        if not conn or not conn.get("is_active"):
            raise AirtableNotFoundError(
                f"Nessuna connessione Airtable attiva per l'organizzazione {organization_id}."
            )

        resolved_base = conn["base_id"]
        token = conn.get("token", "")
        if not token:
            raise AirtableNotFoundError("Token di accesso Airtable non disponibile per il tenant.")

        if self.port_factory:
            port = self.port_factory(token, resolved_base)
        else:
            from src.integrations.airtable.adapter import (
                AirtableAdapter,
                get_shared_rate_limiter,
                get_shared_schema_cache,
            )
            port = AirtableAdapter(
                token=token,
                default_base_id=resolved_base,
                rate_limiter=get_shared_rate_limiter(),
                schema_cache=get_shared_schema_cache(),
            )

        return port, resolved_base

    async def _resolve_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        entity_type: str,
    ) -> TableFieldMapping:
        """Risolve il mapping configurato per l'entità richiesta."""
        clean_entity = entity_type.strip().lower()
        if clean_entity not in ALLOWED_AI_ENTITIES:
            raise AirtableValidationError(
                f"Tipo entità '{entity_type}' non consentito all'AI. Entità permesse: {sorted(ALLOWED_AI_ENTITIES)}"
            )

        if not self.mapping_repo:
            raise AirtableNotFoundError("Repository dei mapping non configurato.")

        mapping = await self.mapping_repo.get_mapping_by_entity(organization_id, base_id, clean_entity)
        if not mapping or not mapping.is_active:
            raise AirtableMissingFieldMappingError(
                missing_fields=[],
                entity_type=clean_entity,
                table_id_or_name="",
                message=(
                    f"Nessuna tabella configurata o attiva nel CRM Airtable per l'entità '{clean_entity}'. "
                    "Configurare il mapping tabella prima di utilizzare le capability AI."
                ),
            )
        return mapping

    # ── CAPABILITY CRM PER L'AI ──────────────────────────────────────────────

    async def find_customer(
        self,
        organization_id: uuid.UUID | str,
        phone: str | None = None,
        email: str | None = None,
        name: str | None = None,
        base_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cerca uno o più clienti nel CRM Airtable per telefono, email o nome."""
        port, b_id = await self._resolve_port_and_base(organization_id, base_id)
        mapping = await self._resolve_mapping(organization_id, b_id, "customer")

        conditions = []
        col_phone = mapping.get_airtable_field("customer.phone")
        if phone and col_phone:
            # Normalizzazione minima per confronto telefonico
            clean_phone = _escape_formula_str(re.sub(r"[^\d+]", "", phone))
            if clean_phone:
                conditions.append(f"FIND('{clean_phone}', {{{col_phone}}}) > 0")

        col_email = mapping.get_airtable_field("customer.email")
        if email and col_email:
            clean_email = _escape_formula_str(email.strip().lower())
            if clean_email:
                conditions.append(f"LOWER({{{col_email}}}) = '{clean_email}'")

        col_name = mapping.get_airtable_field("customer.name")
        if name and col_name:
            clean_name = _escape_formula_str(name.strip().lower())
            if clean_name:
                conditions.append(f"FIND('{clean_name}', LOWER({{{col_name}}})) > 0")

        if not conditions:
            return []

        formula = f"OR({', '.join(conditions)})" if len(conditions) > 1 else conditions[0]

        records = await port.search_records(
            base_id=b_id,
            table_id_or_name=mapping.table_id_or_name,
            formula=formula,
            max_records=5,
        )

        results = []
        for record in records:
            internal = mapping.transform_from_airtable(record.fields)
            results.append({"id": record.id, **internal})
        return results

    async def create_customer(
        self,
        organization_id: uuid.UUID | str,
        name: str,
        phone: str,
        email: str | None = None,
        notes: str | None = None,
        base_id: str | None = None,
    ) -> dict[str, Any]:
        """Crea un nuovo cliente in Airtable applicando validazione e mapping."""
        port, b_id = await self._resolve_port_and_base(organization_id, base_id)
        mapping = await self._resolve_mapping(organization_id, b_id, "customer")

        internal_payload = {
            "customer.name": name.strip() if name else "",
            "customer.phone": phone.strip() if phone else "",
        }
        if email:
            internal_payload["customer.email"] = email.strip()
        if notes:
            internal_payload["customer.notes"] = notes.strip()

        # Trasforma con validazione preventiva dei campi obbligatori
        airtable_payload = mapping.transform_to_airtable(internal_payload)

        record = await port.create_record(
            base_id=b_id,
            table_id_or_name=mapping.table_id_or_name,
            request=CreateRecordRequest(fields=airtable_payload),
        )

        res = mapping.transform_from_airtable(record.fields)
        return {"id": record.id, **res}

    async def update_customer(
        self,
        organization_id: uuid.UUID | str,
        customer_id: str,
        name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        notes: str | None = None,
        base_id: str | None = None,
    ) -> dict[str, Any]:
        """Aggiorna i campi specificati di un cliente esistente in Airtable."""
        if not customer_id or not customer_id.strip():
            raise AirtableValidationError("Identificativo 'customer_id' mancante per l'aggiornamento.")

        port, b_id = await self._resolve_port_and_base(organization_id, base_id)
        mapping = await self._resolve_mapping(organization_id, b_id, "customer")

        internal_payload = {}
        if name is not None:
            internal_payload["customer.name"] = name.strip()
        if phone is not None:
            internal_payload["customer.phone"] = phone.strip()
        if email is not None:
            internal_payload["customer.email"] = email.strip()
        if notes is not None:
            internal_payload["customer.notes"] = notes.strip()

        if not internal_payload:
            raise AirtableValidationError("Nessun campo valido fornito per l'aggiornamento del cliente.")

        # Trasformazione selettiva (solo campi indicati)
        airtable_payload = {}
        for k, v in internal_payload.items():
            col = mapping.get_airtable_field(k)
            if col:
                airtable_payload[col] = v

        # Contract canonico: DTO UpdateRecordRequest; replace=False = PATCH (merge parziale).
        record = await port.update_record(
            base_id=b_id,
            table_id_or_name=mapping.table_id_or_name,
            record_id=customer_id.strip(),
            request=UpdateRecordRequest(fields=airtable_payload, replace=False),
        )

        res = mapping.transform_from_airtable(record.fields)
        return {"id": record.id, **res}

    async def create_lead(
        self,
        organization_id: uuid.UUID | str,
        name: str,
        phone: str,
        email: str | None = None,
        source: str | None = None,
        notes: str | None = None,
        base_id: str | None = None,
    ) -> dict[str, Any]:
        """Registra un nuovo lead commerciale nel CRM Airtable."""
        port, b_id = await self._resolve_port_and_base(organization_id, base_id)
        mapping = await self._resolve_mapping(organization_id, b_id, "lead")

        internal_payload = {
            "lead.name": name.strip() if name else "",
            "lead.phone": phone.strip() if phone else "",
        }
        if email:
            internal_payload["lead.email"] = email.strip()
        if source:
            internal_payload["lead.source"] = source.strip()
        if notes:
            internal_payload["lead.notes"] = notes.strip()

        airtable_payload = mapping.transform_to_airtable(internal_payload)

        record = await port.create_record(
            base_id=b_id,
            table_id_or_name=mapping.table_id_or_name,
            request=CreateRecordRequest(fields=airtable_payload),
        )

        res = mapping.transform_from_airtable(record.fields)
        return {"id": record.id, **res}

    async def create_request(
        self,
        organization_id: uuid.UUID | str,
        customer_phone: str,
        details: str,
        customer_name: str | None = None,
        priority: str = "normal",
        base_id: str | None = None,
    ) -> dict[str, Any]:
        """Registra una richiesta o nota operativa da parte del cliente."""
        port, b_id = await self._resolve_port_and_base(organization_id, base_id)
        mapping = await self._resolve_mapping(organization_id, b_id, "request")

        internal_payload = {
            "request.customer_phone": customer_phone.strip() if customer_phone else "",
            "request.details": details.strip() if details else "",
        }
        if customer_name:
            internal_payload["request.customer_name"] = customer_name.strip()
        if priority:
            internal_payload["request.priority"] = priority.strip()

        airtable_payload = mapping.transform_to_airtable(internal_payload)

        record = await port.create_record(
            base_id=b_id,
            table_id_or_name=mapping.table_id_or_name,
            request=CreateRecordRequest(fields=airtable_payload),
        )

        res = mapping.transform_from_airtable(record.fields)
        return {"id": record.id, **res}

    async def create_ticket(
        self,
        organization_id: uuid.UUID | str,
        subject: str,
        contact_phone: str,
        description: str,
        priority: str = "normal",
        base_id: str | None = None,
    ) -> dict[str, Any]:
        """Apre un ticket di supporto o assistenza per il cliente."""
        port, b_id = await self._resolve_port_and_base(organization_id, base_id)
        mapping = await self._resolve_mapping(organization_id, b_id, "ticket")

        internal_payload = {
            "ticket.subject": subject.strip() if subject else "",
            "ticket.contact_phone": contact_phone.strip() if contact_phone else "",
        }
        if description:
            internal_payload["ticket.description"] = description.strip()
        if priority:
            internal_payload["ticket.priority"] = priority.strip()

        airtable_payload = mapping.transform_to_airtable(internal_payload)

        record = await port.create_record(
            base_id=b_id,
            table_id_or_name=mapping.table_id_or_name,
            request=CreateRecordRequest(fields=airtable_payload),
        )

        res = mapping.transform_from_airtable(record.fields)
        return {"id": record.id, **res}

    async def search_records(
        self,
        organization_id: uuid.UUID | str,
        entity_type: str,
        query: str,
        limit: int = 5,
        base_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Esegue una ricerca testuale su qualsiasi entità consentita (customer, lead, request, ticket)."""
        port, b_id = await self._resolve_port_and_base(organization_id, base_id)
        mapping = await self._resolve_mapping(organization_id, b_id, entity_type)

        clean_query = _escape_formula_str(query.strip().lower()) if query else ""
        formula = None

        if clean_query:
            # Cerca su tutti i campi testo mappati per l'entità
            clauses = []
            for col_name in mapping.field_mappings.values():
                clauses.append(f"FIND('{clean_query}', LOWER({{{col_name}}})) > 0")
            if clauses:
                formula = f"OR({', '.join(clauses)})" if len(clauses) > 1 else clauses[0]

        records = await port.search_records(
            base_id=b_id,
            table_id_or_name=mapping.table_id_or_name,
            formula=formula,
            max_records=min(max(1, limit), 20),
        )

        results = []
        for record in records:
            internal = mapping.transform_from_airtable(record.fields)
            results.append({"id": record.id, **internal})
        return results

    # ── WRITE SAFETY & OPERAZIONI DISTRUTTIVE ─────────────────────────────────

    async def delete_record_safe(
        self,
        organization_id: uuid.UUID | str,
        entity_type: str,
        record_id: str,
        confirmation_token: str | None = None,
        base_id: str | None = None,
    ) -> dict[str, Any]:
        """Operazione distruttiva protetta: richiede conferma esplicita per prevenire cancellazioni accidentali.

        Non consente cancellazioni basate su linguaggio naturale ambiguo.
        """
        clean_rec_id = record_id.strip() if record_id else ""
        if not clean_rec_id:
            raise AirtableValidationError("Identificativo 'record_id' mancante per la cancellazione.")

        # Gate di policy e tenant PRIMA della conferma: il divieto medico (GDPR Art. 9)
        # e l'isolamento tenant valgono a prescindere dal token fornito (fail-closed).
        port, b_id = await self._resolve_port_and_base(organization_id, base_id)
        mapping = await self._resolve_mapping(organization_id, b_id, entity_type)

        # Write Safety: token HMAC non fabbricabile dal modello; il token viene emesso
        # solo tramite AirtableConfirmationRequiredError e deve essere confermato.
        expected_token = _compute_delete_confirmation_token(organization_id, entity_type, clean_rec_id)
        if not _verify_delete_confirmation_token(confirmation_token, expected_token):
            raise AirtableConfirmationRequiredError(
                action=f"delete_{entity_type}",
                record_id=clean_rec_id,
                confirmation_token=expected_token,
            )

        res = await port.delete_record(
            base_id=b_id,
            table_id_or_name=mapping.table_id_or_name,
            record_id=clean_rec_id,
        )

        return {
            "status": "deleted",
            "id": res.id,
            "deleted": res.deleted,
            "message": f"Record '{res.id}' eliminato con successo dall'entità '{entity_type}'.",
        }

    # ── DIVIETO MODIFICHE SCHEMA ─────────────────────────────────────────────

    async def create_table(self, *args, **kwargs) -> Any:
        """Blocco di sicurezza: l'AI non può creare tabelle."""
        raise AirtableSchemaModificationProhibitedError()

    async def delete_table(self, *args, **kwargs) -> Any:
        """Blocco di sicurezza: l'AI non può eliminare tabelle."""
        raise AirtableSchemaModificationProhibitedError()

    async def create_field(self, *args, **kwargs) -> Any:
        """Blocco di sicurezza: l'AI non può creare o alterare campi."""
        raise AirtableSchemaModificationProhibitedError()

    async def update_permissions(self, *args, **kwargs) -> Any:
        """Blocco di sicurezza: l'AI non può alterare i permessi della Base o delle tabelle."""
        raise AirtableSchemaModificationProhibitedError()
