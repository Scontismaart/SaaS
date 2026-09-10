"""Tool AI controllati per l'integrazione di Airtable con CrewAI e sistemi ad agenti.

Conforme a:
- Invariante 1 (Tenant Isolation): Nessun parametro organization_id, base_id o token è esposto nello schema LLM.
  Tutti i dati tenant sono vincolati all'istanza del tool dal contesto autenticato di sessione.
- Invariante 5 (No Direct Privileged Actions): Il tool non effettua chiamate HTTP dirette;
  delega interamente all'Application Service (AirtableAIService) e ad AirtablePort.
- Guardrails & Permissions: Nessuna capacità di alterare schemi, tabelle o permessi.
- Write Safety: Le operazioni distruttive richiedono conferma esplicita con token.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import uuid
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from src.integrations.airtable.ai_service import AirtableAIService
from src.integrations.airtable.errors import (
    AirtableConfirmationRequiredError,
    AirtableError,
    AirtableMedicalPolicyError,
    AirtableMissingFieldMappingError,
    AirtableSchemaModificationProhibitedError,
    AirtableValidationError,
)

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    """Esegue una coroutine asincrona sia all'interno che all'esterno di un event loop attivo."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


# ── INPUT SCHEMAS (SOLO PARAMETRI DI BUSINESS - ZERO TENANT LEAKS) ────────────


class FindCustomerInput(BaseModel):
    """Parametri per la ricerca di un cliente nel CRM Airtable."""
    phone: str | None = Field(default=None, description="Numero di telefono del cliente (es. '+393331234567')")
    email: str | None = Field(default=None, description="Indirizzo email del cliente")
    name: str | None = Field(default=None, description="Nome o cognome del cliente")


class CreateCustomerInput(BaseModel):
    """Parametri per la creazione di un nuovo cliente."""
    name: str = Field(description="Nome completo del cliente")
    phone: str = Field(description="Numero di telefono del cliente")
    email: str | None = Field(default=None, description="Indirizzo email (opzionale)")
    notes: str | None = Field(default=None, description="Note o preferenze del cliente")


class UpdateCustomerInput(BaseModel):
    """Parametri per l'aggiornamento anagrafico di un cliente esistente."""
    customer_id: str = Field(description="Identificativo univoco del record cliente in Airtable (es. 'recXXXXXXXXXXXXXX')")
    name: str | None = Field(default=None, description="Nuovo nome completo (se modificato)")
    phone: str | None = Field(default=None, description="Nuovo numero di telefono (se modificato)")
    email: str | None = Field(default=None, description="Nuova email (se modificata)")
    notes: str | None = Field(default=None, description="Note aggiornate (se modificate)")


class CreateLeadInput(BaseModel):
    """Parametri per la registrazione di un nuovo lead commerciale."""
    name: str = Field(description="Nome o ragione sociale del contatto/lead")
    phone: str = Field(description="Numero di telefono del lead")
    email: str | None = Field(default=None, description="Email del lead (opzionale)")
    source: str | None = Field(default=None, description="Canale o provenienza del contatto (es. 'WhatsApp', 'Sito')")
    notes: str | None = Field(default=None, description="Dettagli sulla richiesta commerciale")


class CreateRequestInput(BaseModel):
    """Parametri per registrare una richiesta operativa o nota di follow-up del cliente."""
    customer_phone: str = Field(description="Numero di telefono del cliente richiedente")
    details: str = Field(description="Descrizione dettagliata della richiesta o del follow-up")
    customer_name: str | None = Field(default=None, description="Nome del cliente (opzionale)")
    priority: str = Field(default="normal", description="Priorità della richiesta: 'low', 'normal', 'high'")


class CreateTicketInput(BaseModel):
    """Parametri per l'apertura di un ticket di assistenza clienti."""
    subject: str = Field(description="Oggetto o titolo sintetico del problema/ticket")
    contact_phone: str = Field(description="Numero di telefono del cliente per contatto")
    description: str = Field(description="Descrizione completa della segnalazione o richiesta")
    priority: str = Field(default="normal", description="Priorità del ticket: 'low', 'normal', 'urgent'")


class SearchRecordsInput(BaseModel):
    """Parametri per la ricerca testuale generica tra i record Airtable."""
    entity_type: str = Field(description="Tipo di entità da cercare: 'customer', 'lead', 'request', 'ticket'")
    query: str = Field(description="Parola chiave, nome o testo da cercare")
    limit: int = Field(default=5, description="Numero massimo di risultati da restituire (max 20)")


class DeleteRecordInput(BaseModel):
    """Parametri per l'eliminazione controllata di un record Airtable (Write Safety)."""
    entity_type: str = Field(description="Tipo di entità: 'customer', 'lead', 'request', 'ticket'")
    record_id: str = Field(description="ID del record da eliminare (es. 'recXXXXXXXXXXXXXX')")
    confirmation_token: str | None = Field(
        default=None,
        description=(
            "Token di conferma server-side richiesto per completare la cancellazione. "
            "NON inventare o fabbricare alcun token: se assente, la prima chiamata "
            "restituisce la richiesta di conferma con il token da presentare "
            "all'utente/operatore umano e ripetere la chiamata."
        ),
    )


# ── CREWAI TOOLS CONTROLLATI ──────────────────────────────────────────────────


class FindCustomerTool(BaseTool):
    """Tool per la ricerca di clienti nel CRM Airtable."""
    name: str = "airtable_find_customer"
    description: str = (
        "Cerca un cliente nel CRM Airtable per numero di telefono, email o nome. "
        "Utilizzare prima di creare un nuovo cliente per verificare se esiste già."
    )
    args_schema: type[BaseModel] = FindCustomerInput

    # Campi interni iniettati dall'applicazione (esclusi dal modello LLM)
    service: AirtableAIService = Field(exclude=True)
    organization_id: uuid.UUID = Field(exclude=True)
    base_id: str | None = Field(default=None, exclude=True)

    def _run(self, phone: str | None = None, email: str | None = None, name: str | None = None) -> str:
        return _run_async(self._arun(phone=phone, email=email, name=name))

    async def _arun(self, phone: str | None = None, email: str | None = None, name: str | None = None) -> str:
        try:
            results = await self.service.find_customer(
                organization_id=self.organization_id,
                phone=phone,
                email=email,
                name=name,
                base_id=self.base_id,
            )
            if not results:
                return "Nessun cliente trovato con i criteri specificati."
            return json.dumps(results, ensure_ascii=False)
        except AirtableMedicalPolicyError as exc:
            return f"ERRORE DI POLICY: {exc.message}"
        except AirtableError as exc:
            return f"ERRORE AIRTABLE: {exc.message}"


class CreateCustomerTool(BaseTool):
    """Tool per la registrazione di nuovi clienti in Airtable."""
    name: str = "airtable_create_customer"
    description: str = (
        "Registra un nuovo cliente nel CRM Airtable con nome, telefono, email e note. "
        "Tutti i dati vengono validati e mappati automaticamente."
    )
    args_schema: type[BaseModel] = CreateCustomerInput

    service: AirtableAIService = Field(exclude=True)
    organization_id: uuid.UUID = Field(exclude=True)
    base_id: str | None = Field(default=None, exclude=True)

    def _run(self, name: str, phone: str, email: str | None = None, notes: str | None = None) -> str:
        return _run_async(self._arun(name=name, phone=phone, email=email, notes=notes))

    async def _arun(self, name: str, phone: str, email: str | None = None, notes: str | None = None) -> str:
        try:
            res = await self.service.create_customer(
                organization_id=self.organization_id,
                name=name,
                phone=phone,
                email=email,
                notes=notes,
                base_id=self.base_id,
            )
            return f"Cliente creato con successo: ID={res.get('id')}, Dati={json.dumps(res, ensure_ascii=False)}"
        except AirtableMedicalPolicyError as exc:
            return f"ERRORE DI POLICY: {exc.message}"
        except AirtableError as exc:
            return f"ERRORE AIRTABLE: {exc.message}"


class UpdateCustomerTool(BaseTool):
    """Tool per l'aggiornamento di clienti esistenti in Airtable."""
    name: str = "airtable_update_customer"
    description: str = (
        "Aggiorna le informazioni anagrafiche o note di un cliente esistente in Airtable "
        "fornendo il suo record ID ('recXXXXXXXX')."
    )
    args_schema: type[BaseModel] = UpdateCustomerInput

    service: AirtableAIService = Field(exclude=True)
    organization_id: uuid.UUID = Field(exclude=True)
    base_id: str | None = Field(default=None, exclude=True)

    def _run(
        self,
        customer_id: str,
        name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        notes: str | None = None,
    ) -> str:
        return _run_async(self._arun(customer_id=customer_id, name=name, phone=phone, email=email, notes=notes))

    async def _arun(
        self,
        customer_id: str,
        name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        notes: str | None = None,
    ) -> str:
        try:
            res = await self.service.update_customer(
                organization_id=self.organization_id,
                customer_id=customer_id,
                name=name,
                phone=phone,
                email=email,
                notes=notes,
                base_id=self.base_id,
            )
            return f"Cliente aggiornato con successo: {json.dumps(res, ensure_ascii=False)}"
        except AirtableMedicalPolicyError as exc:
            return f"ERRORE DI POLICY: {exc.message}"
        except AirtableError as exc:
            return f"ERRORE AIRTABLE: {exc.message}"


class CreateLeadTool(BaseTool):
    """Tool per la creazione di opportunità/lead commerciali."""
    name: str = "airtable_create_lead"
    description: str = "Registra un nuovo lead commerciale nel CRM Airtable per contatti interessati ai servizi."
    args_schema: type[BaseModel] = CreateLeadInput

    service: AirtableAIService = Field(exclude=True)
    organization_id: uuid.UUID = Field(exclude=True)
    base_id: str | None = Field(default=None, exclude=True)

    def _run(self, name: str, phone: str, email: str | None = None, source: str | None = None, notes: str | None = None) -> str:
        return _run_async(self._arun(name=name, phone=phone, email=email, source=source, notes=notes))

    async def _arun(self, name: str, phone: str, email: str | None = None, source: str | None = None, notes: str | None = None) -> str:
        try:
            res = await self.service.create_lead(
                organization_id=self.organization_id,
                name=name,
                phone=phone,
                email=email,
                source=source,
                notes=notes,
                base_id=self.base_id,
            )
            return f"Lead registrato con successo: ID={res.get('id')}, Dati={json.dumps(res, ensure_ascii=False)}"
        except AirtableMedicalPolicyError as exc:
            return f"ERRORE DI POLICY: {exc.message}"
        except AirtableError as exc:
            return f"ERRORE AIRTABLE: {exc.message}"


class CreateRequestTool(BaseTool):
    """Tool per registrare richieste operative da parte dei clienti."""
    name: str = "airtable_create_request"
    description: str = "Registra una richiesta operativa o messaggio di follow-up da parte del cliente su Airtable."
    args_schema: type[BaseModel] = CreateRequestInput

    service: AirtableAIService = Field(exclude=True)
    organization_id: uuid.UUID = Field(exclude=True)
    base_id: str | None = Field(default=None, exclude=True)

    def _run(self, customer_phone: str, details: str, customer_name: str | None = None, priority: str = "normal") -> str:
        return _run_async(self._arun(customer_phone=customer_phone, details=details, customer_name=customer_name, priority=priority))

    async def _arun(self, customer_phone: str, details: str, customer_name: str | None = None, priority: str = "normal") -> str:
        try:
            res = await self.service.create_request(
                organization_id=self.organization_id,
                customer_phone=customer_phone,
                details=details,
                customer_name=customer_name,
                priority=priority,
                base_id=self.base_id,
            )
            return f"Richiesta registrata con successo: ID={res.get('id')}, Dati={json.dumps(res, ensure_ascii=False)}"
        except AirtableMedicalPolicyError as exc:
            return f"ERRORE DI POLICY: {exc.message}"
        except AirtableError as exc:
            return f"ERRORE AIRTABLE: {exc.message}"


class CreateTicketTool(BaseTool):
    """Tool per l'apertura di ticket di supporto."""
    name: str = "airtable_create_ticket"
    description: str = "Apre un ticket di supporto per segnalazioni, problemi o richieste complesse del cliente."
    args_schema: type[BaseModel] = CreateTicketInput

    service: AirtableAIService = Field(exclude=True)
    organization_id: uuid.UUID = Field(exclude=True)
    base_id: str | None = Field(default=None, exclude=True)

    def _run(self, subject: str, contact_phone: str, description: str, priority: str = "normal") -> str:
        return _run_async(self._arun(subject=subject, contact_phone=contact_phone, description=description, priority=priority))

    async def _arun(self, subject: str, contact_phone: str, description: str, priority: str = "normal") -> str:
        try:
            res = await self.service.create_ticket(
                organization_id=self.organization_id,
                subject=subject,
                contact_phone=contact_phone,
                description=description,
                priority=priority,
                base_id=self.base_id,
            )
            return f"Ticket aperto con successo: ID={res.get('id')}, Dati={json.dumps(res, ensure_ascii=False)}"
        except AirtableMedicalPolicyError as exc:
            return f"ERRORE DI POLICY: {exc.message}"
        except AirtableError as exc:
            return f"ERRORE AIRTABLE: {exc.message}"


class SearchRecordsTool(BaseTool):
    """Tool per ricerca generica sicura tra i record del CRM Airtable."""
    name: str = "airtable_search_records"
    description: str = (
        "Cerca record nel CRM Airtable per entità ('customer', 'lead', 'request', 'ticket') e testo. "
        "Filtra automaticamente per il tenant corrente e neutralizza tentativi di injection."
    )
    args_schema: type[BaseModel] = SearchRecordsInput

    service: AirtableAIService = Field(exclude=True)
    organization_id: uuid.UUID = Field(exclude=True)
    base_id: str | None = Field(default=None, exclude=True)

    def _run(self, entity_type: str, query: str, limit: int = 5) -> str:
        return _run_async(self._arun(entity_type=entity_type, query=query, limit=limit))

    async def _arun(self, entity_type: str, query: str, limit: int = 5) -> str:
        try:
            records = await self.service.search_records(
                organization_id=self.organization_id,
                entity_type=entity_type,
                query=query,
                limit=limit,
                base_id=self.base_id,
            )
            if not records:
                return f"Nessun record trovato per '{query}' nell'entità '{entity_type}'."
            return json.dumps(records, ensure_ascii=False)
        except AirtableMedicalPolicyError as exc:
            return f"ERRORE DI POLICY: {exc.message}"
        except AirtableError as exc:
            return f"ERRORE AIRTABLE: {exc.message}"


class DeleteRecordTool(BaseTool):
    """Tool protetto per eliminazione record con write safety (conferma esplicita obbligatoria)."""
    name: str = "airtable_delete_record"
    description: str = (
        "Elimina un record da Airtable. Operazione distruttiva protetta: richiede il parametro "
        "'confirmation_token'. Se non fornito, il tool NON elimina nulla e restituisce il token richiesto."
    )
    args_schema: type[BaseModel] = DeleteRecordInput

    service: AirtableAIService = Field(exclude=True)
    organization_id: uuid.UUID = Field(exclude=True)
    base_id: str | None = Field(default=None, exclude=True)

    def _run(self, entity_type: str, record_id: str, confirmation_token: str | None = None) -> str:
        return _run_async(self._arun(entity_type=entity_type, record_id=record_id, confirmation_token=confirmation_token))

    async def _arun(self, entity_type: str, record_id: str, confirmation_token: str | None = None) -> str:
        try:
            res = await self.service.delete_record_safe(
                organization_id=self.organization_id,
                entity_type=entity_type,
                record_id=record_id,
                confirmation_token=confirmation_token,
                base_id=self.base_id,
            )
            return f"Record eliminato con successo: {json.dumps(res, ensure_ascii=False)}"
        except AirtableConfirmationRequiredError as exc:
            return (
                f"RICHIESTA DI CONFERMA: {exc.message} "
                f"Chiedere conferma all'utente/operatore e ripetere la chiamata con confirmation_token='{exc.confirmation_token}'."
            )
        except AirtableMedicalPolicyError as exc:
            return f"ERRORE DI POLICY: {exc.message}"
        except AirtableError as exc:
            return f"ERRORE AIRTABLE: {exc.message}"


# ── FACTORY PER L'ORCHESTRATORE / AGENTE ──────────────────────────────────────


def create_airtable_tools(
    service: AirtableAIService,
    organization_id: uuid.UUID | str,
    base_id: str | None = None,
) -> list[BaseTool]:
    """Crea la suite completa di tool AI per Airtable pre-vincolati al tenant autenticato.

    Garantisce l'Invariante 1 (Tenant Isolation):
    Nessun tool accetta organization_id o token dal modello LLM.
    """
    org_uuid = uuid.UUID(str(organization_id))
    return [
        FindCustomerTool(service=service, organization_id=org_uuid, base_id=base_id),
        CreateCustomerTool(service=service, organization_id=org_uuid, base_id=base_id),
        UpdateCustomerTool(service=service, organization_id=org_uuid, base_id=base_id),
        CreateLeadTool(service=service, organization_id=org_uuid, base_id=base_id),
        CreateRequestTool(service=service, organization_id=org_uuid, base_id=base_id),
        CreateTicketTool(service=service, organization_id=org_uuid, base_id=base_id),
        SearchRecordsTool(service=service, organization_id=org_uuid, base_id=base_id),
        DeleteRecordTool(service=service, organization_id=org_uuid, base_id=base_id),
    ]
