from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from typing import Any

import asyncpg

from src.core.db.repositories.billing_repo import BillingRepository
from src.core.db.repositories.booking_repo import BookingRepository
from src.core.db.repositories.contact_repo import ContactRepository
from src.core.db.repositories.conversation_repo import ConversationRepository
from src.core.db.repositories.document_repo import DocumentRepository
from src.core.db.repositories.message_repo import MessageRepository
from src.core.db.repositories.organization_repo import OrganizationRepository
from src.core.db.repositories.review_repo import ReviewRepository
from src.core.db.scoping import TenantScopedRepository, system_scope


class CoreRepository(TenantScopedRepository):
    """Facade di retrocompatibilità per CoreRepository.

    Delega tutte le chiamate ai repository specializzati per dominio:
    - OrganizationRepository
    - ContactRepository
    - ConversationRepository
    - MessageRepository
    - BookingRepository
    - DocumentRepository
    - ReviewRepository
    - BillingRepository
    """

    _CAMPI_REVIEW_AGGIORNABILI = ReviewRepository._CAMPI_REVIEW_AGGIORNABILI

    def __init__(self, pool):
        self.pool = pool
        self._org_repo = OrganizationRepository(pool)
        self._booking_repo = BookingRepository(pool)
        self._doc_repo = DocumentRepository(pool)
        self._review_repo = ReviewRepository(pool)
        self._billing_repo = BillingRepository(pool)
        self._contact_repo = ContactRepository(pool)
        self._conv_repo = ConversationRepository(pool)
        self._msg_repo = MessageRepository(pool)

        # Accesso diretto ai sotto-repository per migrazione progressiva
        self.org_repo = self._org_repo
        self.booking_repo = self._booking_repo
        self.doc_repo = self._doc_repo
        self.review_repo = self._review_repo
        self.billing_repo = self._billing_repo
        self.contact_repo = self._contact_repo
        self.conv_repo = self._conv_repo
        self.msg_repo = self._msg_repo

    # ── Bookings ──────────────────────────────────────────────

    @asynccontextmanager
    async def slot_lock(self, organization_id, data, ora):
        """Lock consultivo transazionale su una fascia oraria (anti double-booking)."""
        async with self._booking_repo.slot_lock(organization_id, data, ora):
            yield

    async def create_booking(self, organization_id, nome_cliente, data, ora, coperti,
                             telefono="", note="", stato="in_attesa", origine="Dashboard",
                             richiede_intervento=False, id_conversazione=None,
                             contact_id=None, richiede_deposito=False,
                             completata_at=None, tipo_evento="", source_message_id=None):
        return await self._booking_repo.create_booking(
            organization_id, nome_cliente, data, ora, coperti,
            telefono=telefono, note=note, stato=stato, origine=origine,
            richiede_intervento=richiede_intervento, id_conversazione=id_conversazione,
            contact_id=contact_id, richiede_deposito=richiede_deposito,
            completata_at=completata_at, tipo_evento=tipo_evento, source_message_id=source_message_id,
        )

    async def get_booking(self, organization_id, booking_id):
        return await self._booking_repo.get_booking(organization_id, booking_id)

    async def list_bookings(self, organization_id, data=None, da_data=None, a_data=None):
        return await self._booking_repo.list_bookings(
            organization_id, data=data, da_data=da_data, a_data=a_data
        )

    async def list_bookings_by_stato(self, organization_id, stato):
        return await self._booking_repo.list_bookings_by_stato(organization_id, stato)

    async def list_bookings_da_verificare(self, organization_id):
        return await self._booking_repo.list_bookings_da_verificare(organization_id)

    async def list_bookings_for_reminder(self, target_date, ore_anticipo=24):
        return await self._booking_repo.list_bookings_for_reminder(target_date, ore_anticipo=ore_anticipo)

    async def update_booking_reminder_status(self, organization_id, booking_id, status):
        return await self._booking_repo.update_booking_reminder_status(organization_id, booking_id, status)

    async def update_booking_status(self, organization_id, booking_id, stato,
                                    note=None, richiede_intervento=None,
                                    richiede_deposito=None, completata_at=None,
                                    deposit_payment_id=None,
                                    deposit_amount=None,
                                    deposit_status=None):
        return await self._booking_repo.update_booking_status(
            organization_id, booking_id, stato,
            note=note, richiede_intervento=richiede_intervento,
            richiede_deposito=richiede_deposito, completata_at=completata_at,
            deposit_payment_id=deposit_payment_id,
            deposit_amount=deposit_amount,
            deposit_status=deposit_status,
        )

    async def update_booking_details(self, organization_id, booking_id, **kwargs):
        return await self._booking_repo.update_booking_details(organization_id, booking_id, **kwargs)

    async def update_booking_payment(self, organization_id, booking_id, payment_intent_id, status):
        return await self._booking_repo.update_booking_payment(
            organization_id, booking_id, payment_intent_id, status
        )

    async def get_booking_settings(self, organization_id):
        return await self._booking_repo.get_booking_settings(organization_id)

    async def upsert_booking_settings(self, organization_id, max_coperti_per_slot=None,
                                       intervallo_slot_minuti=None,
                                       ora_inizio_pranzo=None, ora_fine_pranzo=None,
                                       ora_inizio_cena=None, ora_fine_cena=None,
                                       giorni_apertura=None,
                                       richiede_deposito_standard=None,
                                       importo_deposito_standard=None):
        return await self._booking_repo.upsert_booking_settings(
            organization_id, max_coperti_per_slot=max_coperti_per_slot,
            intervallo_slot_minuti=intervallo_slot_minuti,
            ora_inizio_pranzo=ora_inizio_pranzo, ora_fine_pranzo=ora_fine_pranzo,
            ora_inizio_cena=ora_inizio_cena, ora_fine_cena=ora_fine_cena,
            giorni_apertura=giorni_apertura,
            richiede_deposito_standard=richiede_deposito_standard,
            importo_deposito_standard=importo_deposito_standard,
        )

    async def upsert_booking_settings_config(self, organization_id, config_dict: dict):
        return await self._booking_repo.upsert_booking_settings_config(organization_id, config_dict)

    # ── Reviews ───────────────────────────────────────────────

    async def create_review(self, organization_id, testo, voto, fonte,
                            autore="", external_id=None, sentiment=None,
                            risposta_bozza="", risposta_pubblicata="",
                            stato="da_approvare", recensito_at=None,
                            raw_data=None):
        return await self._review_repo.create_review(
            organization_id, testo, voto, fonte,
            autore=autore, external_id=external_id, sentiment=sentiment,
            risposta_bozza=risposta_bozza, risposta_pubblicata=risposta_pubblicata,
            stato=stato, recensito_at=recensito_at, raw_data=raw_data,
        )

    async def get_review(self, organization_id, review_id):
        return await self._review_repo.get_review(organization_id, review_id)

    async def get_review_by_external_id(self, organization_id, external_id):
        return await self._review_repo.get_review_by_external_id(organization_id, external_id)

    async def list_reviews(self, organization_id, stato=None, fonte=None,
                           page=1, limit=20):
        return await self._review_repo.list_reviews(
            organization_id, stato=stato, fonte=fonte, page=page, limit=limit
        )

    async def update_review(self, organization_id, review_id, **kwargs):
        return await self._review_repo.update_review(organization_id, review_id, **kwargs)

    async def approve_review(self, organization_id, review_id, risposta_finale=None):
        return await self._review_repo.approve_review(
            organization_id, review_id, risposta_finale=risposta_finale
        )

    async def get_review_analytics(self, organization_id, da_data=None, a_data=None):
        return await self._review_repo.get_review_analytics(organization_id, da_data=da_data, a_data=a_data)

    async def get_ui_summary(self, organization_id):
        return await self._review_repo.get_ui_summary(organization_id)

    # ── Knowledge Base (RAG) ──────────────────────────────────

    async def create_document(self, organization_id, filename, source,
                              file_size_bytes, mime_type, chunk_count=0):
        return await self._doc_repo.create_document(
            organization_id, filename, source, file_size_bytes, mime_type, chunk_count=chunk_count
        )

    async def get_document(self, organization_id, document_id):
        return await self._doc_repo.get_document(organization_id, document_id)

    async def list_documents(self, organization_id, is_active=None):
        return await self._doc_repo.list_documents(organization_id, is_active=is_active)

    async def update_document(self, organization_id, document_id, **kwargs):
        return await self._doc_repo.update_document(organization_id, document_id, **kwargs)

    async def delete_document(self, organization_id, document_id):
        return await self._doc_repo.delete_document(organization_id, document_id)

    async def toggle_document_active(self, organization_id, document_id, is_active):
        return await self._doc_repo.toggle_document_active(organization_id, document_id, is_active)

    async def add_chunk(self, organization_id, document_id, chunk_index,
                        chunk_text, embedding=None, token_count=None):
        return await self._doc_repo.add_chunk(
            organization_id, document_id, chunk_index, chunk_text,
            embedding=embedding, token_count=token_count,
        )

    async def delete_document_chunks(self, organization_id, document_id):
        return await self._doc_repo.delete_document_chunks(organization_id, document_id)

    async def search_similar(self, organization_id, query_embedding,
                             top_k=3, similarity_threshold=0.3, only_active=True):
        return await self._doc_repo.search_similar(
            organization_id, query_embedding, top_k=top_k,
            similarity_threshold=similarity_threshold, only_active=only_active,
        )

    async def count_chunks(self, organization_id, document_id=None):
        return await self._doc_repo.count_chunks(organization_id, document_id=document_id)

    async def list_sources(self, organization_id):
        return await self._doc_repo.list_sources(organization_id)

    async def list_all_active_chunks(self, organization_id):
        return await self._doc_repo.list_all_active_chunks(organization_id)

    async def faq_cache_invalidate(self, organization_id):
        return await self._doc_repo.faq_cache_invalidate(organization_id)

    # ── Email Configurations ──────────────────────────────────

    async def add_email_config(self, organization_id, email, label="default",
                               provider="resend", api_key="", is_active=True):
        return await self._org_repo.add_email_config(
            organization_id, email, label=label, provider=provider, api_key=api_key, is_active=is_active
        )

    async def list_email_configs(self, organization_id):
        return await self._org_repo.list_email_configs(organization_id)

    async def remove_email_config(self, organization_id, config_id):
        return await self._org_repo.remove_email_config(organization_id, config_id)

    # ── Business Profile & Onboarding ─────────────────────────

    async def get_org_business_profile(self, organization_id):
        return await self._org_repo.get_org_business_profile(organization_id)

    async def update_org_business_profile(self, organization_id, profile: dict):
        return await self._org_repo.update_org_business_profile(organization_id, profile)

    @staticmethod
    def _json_fields_onboarding(profile: dict) -> dict:
        return OrganizationRepository._json_fields_onboarding(profile)

    async def save_onboarding_profile(
        self,
        organization_id: uuid.UUID | str,
        profile: dict,
        stato: str = "completato",
    ) -> dict:
        return await self._org_repo.save_onboarding_profile(organization_id, profile, stato=stato)

    async def get_onboarding_profile(
        self, organization_id: uuid.UUID | str
    ) -> dict | None:
        return await self._org_repo.get_onboarding_profile(organization_id)

    async def get_organization(self, organization_id: uuid.UUID | str) -> dict | None:
        return await self._org_repo.get_organization(organization_id)

    # ── Usage events ──────────────────────────────────────────

    async def record_usage(self, organization_id, event_type, quantity=1,
                            metadata=None):
        return await self._billing_repo.record_usage(
            organization_id, event_type, quantity=quantity, metadata=metadata
        )

    async def get_usage_by_month(self, organization_id, year, month):
        return await self._billing_repo.get_usage_by_month(organization_id, year, month)

    async def get_usage_summary(self, organization_id, year, month):
        return await self._billing_repo.get_usage_summary(organization_id, year, month)

    # ── Auth & Memberships ────────────────────────────────────

    async def get_membership_by_auth(self, auth_user_id: str) -> dict | None:
        return await self._org_repo.get_membership_by_auth(auth_user_id)

    async def get_memberships_by_auth(self, auth_user_id: str) -> list[dict]:
        return await self._org_repo.get_memberships_by_auth(auth_user_id)

    # ── Billing & Abbonamento ─────────────────────────────────

    async def get_organization_billing(self, organization_id: uuid.UUID | str) -> dict:
        return await self._billing_repo.get_organization_billing(organization_id)

    async def update_organization_billing(
        self, organization_id: uuid.UUID | str, data: dict
    ) -> dict:
        return await self._billing_repo.update_organization_billing(organization_id, data)

    async def set_subscription_status(
        self, organization_id: uuid.UUID | str, status: str
    ) -> None:
        return await self._billing_repo.set_subscription_status(organization_id, status)

    async def increment_message_usage(
        self, organization_id: uuid.UUID | str
    ) -> int | None:
        return await self._billing_repo.increment_message_usage(organization_id)

    async def reset_message_usage(
        self,
        organization_id: uuid.UUID | str,
        period_start: datetime,
        period_end: datetime,
    ) -> None:
        return await self._billing_repo.reset_message_usage(organization_id, period_start, period_end)

    async def process_stripe_event(
        self, event_id: str, organization_id: uuid.UUID | str
    ) -> bool:
        return await self._billing_repo.process_stripe_event(event_id, organization_id)

    async def process_stripe_event_in_tx(
        self, conn, event_id: str, organization_id: uuid.UUID | str
    ) -> bool:
        return await self._billing_repo.process_stripe_event_in_tx(conn, event_id, organization_id)

    async def update_plan_limits(
        self, organization_id: uuid.UUID | str, plan_slug: str
    ) -> dict:
        return await self._billing_repo.update_plan_limits(organization_id, plan_slug)

    @system_scope("risoluzione tenant da stripe_customer_id platform-unique")
    async def get_organization_by_stripe_customer(
        self, stripe_customer_id: str
    ) -> dict | None:
        return await self._billing_repo.get_organization_by_stripe_customer(stripe_customer_id)

    # ── GDPR ─────────────────────────────────────────────────────

    async def get_contacts_by_org(self, organization_id: uuid.UUID | str) -> list[dict]:
        return await self._contact_repo.get_contacts_by_org(organization_id)

    async def get_conversations_by_org(self, organization_id: uuid.UUID | str) -> list[dict]:
        return await self._conv_repo.get_conversations_by_org(organization_id)

    async def get_messages_by_org(self, organization_id: uuid.UUID | str) -> list[dict]:
        return await self._msg_repo.get_messages_by_org(organization_id)

    async def get_organization_owners(self, org_id: str) -> list[dict]:
        return await self._org_repo.get_organization_owners(org_id)

    @system_scope("root PK delete, cascade DB, endpoint owner-only")
    async def delete_organization(self, organization_id: uuid.UUID | str) -> None:
        return await self._org_repo.delete_organization(organization_id)

    # ── Registrazione (system scope: l'org non esiste ancora) ──

    async def create_organization_with_owner(
        self,
        auth_user_id: str,
        nome_attivita: str,
        trial_days: int = 14,
    ) -> dict:
        return await self._org_repo.create_organization_with_owner(
            auth_user_id, nome_attivita, trial_days=trial_days
        )

    @system_scope("provisioning JIT org al primo accesso OAuth")
    async def get_or_create_organization_with_owner(
        self,
        auth_user_id: str,
        nome_attivita: str,
        trial_days: int = 7,
    ) -> dict:
        return await self._org_repo.get_or_create_organization_with_owner(
            auth_user_id, nome_attivita, trial_days=trial_days
        )
