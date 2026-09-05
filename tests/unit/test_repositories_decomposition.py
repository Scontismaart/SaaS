"""Test unitari per la decomposizione dei repository (Fase 1).

Verifica che le facade CoreRepository e WhatsAppRepository deleghino
correttamente le chiamate ai rispettivi repository specializzati per dominio.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.core.db.repositories.billing_repo import BillingRepository
from src.core.db.repositories.booking_repo import BookingRepository
from src.core.db.repositories.contact_repo import ContactRepository
from src.core.db.repositories.conversation_repo import ConversationRepository
from src.core.db.repositories.document_repo import DocumentRepository
from src.core.db.repositories.message_repo import MessageRepository
from src.core.db.repositories.organization_repo import OrganizationRepository
from src.core.db.repositories.review_repo import ReviewRepository
from src.core.db.repository import CoreRepository
from src.whatsapp.repository import Repository as WhatsAppRepository


def test_specialized_repositories_instantiation():
    mock_pool = MagicMock()
    repos = [
        OrganizationRepository(mock_pool),
        ContactRepository(mock_pool),
        ConversationRepository(mock_pool),
        MessageRepository(mock_pool),
        BookingRepository(mock_pool),
        DocumentRepository(mock_pool),
        ReviewRepository(mock_pool),
        BillingRepository(mock_pool),
    ]
    for repo in repos:
        assert repo.pool is mock_pool


def test_core_repository_facade_subrepos_exposed():
    mock_pool = MagicMock()
    core_repo = CoreRepository(mock_pool)
    assert isinstance(core_repo.org_repo, OrganizationRepository)
    assert isinstance(core_repo.booking_repo, BookingRepository)
    assert isinstance(core_repo.doc_repo, DocumentRepository)
    assert isinstance(core_repo.review_repo, ReviewRepository)
    assert isinstance(core_repo.billing_repo, BillingRepository)
    assert isinstance(core_repo.contact_repo, ContactRepository)
    assert isinstance(core_repo.conv_repo, ConversationRepository)
    assert isinstance(core_repo.msg_repo, MessageRepository)


def test_whatsapp_repository_facade_subrepos_exposed():
    mock_pool = MagicMock()
    wa_repo = WhatsAppRepository(mock_pool)
    assert isinstance(wa_repo.org_repo, OrganizationRepository)
    assert isinstance(wa_repo.contact_repo, ContactRepository)
    assert isinstance(wa_repo.conv_repo, ConversationRepository)
    assert isinstance(wa_repo.msg_repo, MessageRepository)
    assert isinstance(wa_repo.booking_repo, BookingRepository)
    assert isinstance(wa_repo.doc_repo, DocumentRepository)
    assert isinstance(wa_repo.billing_repo, BillingRepository)


@pytest.mark.asyncio
async def test_core_repo_delegates_to_specialized():
    mock_pool = MagicMock()
    core_repo = CoreRepository(mock_pool)
    org_id = uuid.uuid4()

    # Mock each underlying sub-repo method
    core_repo._org_repo.get_organization = AsyncMock(return_value={"id": org_id, "name": "Test Org"})
    core_repo._booking_repo.get_booking = AsyncMock(return_value={"id": 1, "nome_cliente": "Mario"})
    core_repo._review_repo.get_review = AsyncMock(return_value={"id": 1, "voto": 5})
    core_repo._doc_repo.get_document = AsyncMock(return_value={"id": 1, "filename": "doc.pdf"})
    core_repo._billing_repo.get_organization_billing = AsyncMock(return_value={"plan": "pro"})
    core_repo._contact_repo.get_contacts_by_org = AsyncMock(return_value=[])
    core_repo._conv_repo.get_conversations_by_org = AsyncMock(return_value=[])
    core_repo._msg_repo.get_messages_by_org = AsyncMock(return_value=[])

    # Call through facade
    res_org = await core_repo.get_organization(org_id)
    assert res_org["name"] == "Test Org"
    core_repo._org_repo.get_organization.assert_awaited_once_with(org_id)

    res_booking = await core_repo.get_booking(org_id, 1)
    assert res_booking["nome_cliente"] == "Mario"
    core_repo._booking_repo.get_booking.assert_awaited_once_with(org_id, 1)

    res_review = await core_repo.get_review(org_id, 1)
    assert res_review["voto"] == 5
    core_repo._review_repo.get_review.assert_awaited_once_with(org_id, 1)

    res_doc = await core_repo.get_document(org_id, 1)
    assert res_doc["filename"] == "doc.pdf"
    core_repo._doc_repo.get_document.assert_awaited_once_with(org_id, 1)

    res_bill = await core_repo.get_organization_billing(org_id)
    assert res_bill["plan"] == "pro"
    core_repo._billing_repo.get_organization_billing.assert_awaited_once_with(org_id)

    res_contacts = await core_repo.get_contacts_by_org(org_id)
    assert res_contacts == []
    core_repo._contact_repo.get_contacts_by_org.assert_awaited_once_with(org_id)

    res_convs = await core_repo.get_conversations_by_org(org_id)
    assert res_convs == []
    core_repo._conv_repo.get_conversations_by_org.assert_awaited_once_with(org_id)

    res_msgs = await core_repo.get_messages_by_org(org_id)
    assert res_msgs == []
    core_repo._msg_repo.get_messages_by_org.assert_awaited_once_with(org_id)


@pytest.mark.asyncio
async def test_whatsapp_repo_delegates_to_specialized():
    mock_pool = MagicMock()
    wa_repo = WhatsAppRepository(mock_pool)
    org_id = uuid.uuid4()
    msg_id = uuid.uuid4()

    # Mock underlying sub-repo methods
    wa_repo._org_repo.get_org_by_phone_number_id = AsyncMock(return_value={"organization_id": org_id})
    wa_repo._contact_repo.get_or_create_contact = AsyncMock(return_value={"id": 1, "wa_id": "39123"})
    wa_repo._conv_repo.get_or_create_conversation = AsyncMock(return_value={"id": 10})
    wa_repo._msg_repo.check_idempotency = AsyncMock(return_value=False)
    wa_repo._booking_repo.check_booking_exists = AsyncMock(return_value=False)
    wa_repo._doc_repo.faq_cache_lookup = AsyncMock(return_value=None)
    wa_repo._billing_repo.check_message_usage = AsyncMock(return_value={"messages_used_this_period": 5})

    # Call through facade
    res_lookup = await wa_repo.get_org_by_phone_number_id("123456")
    assert res_lookup["organization_id"] == org_id
    wa_repo._org_repo.get_org_by_phone_number_id.assert_awaited_once_with("123456")

    res_contact = await wa_repo.get_or_create_contact(org_id, "39123")
    assert res_contact["id"] == 1
    wa_repo._contact_repo.get_or_create_contact.assert_awaited_once_with(org_id, "39123", profile_name=None)

    res_conv = await wa_repo.get_or_create_conversation(org_id, 1)
    assert res_conv["id"] == 10
    wa_repo._conv_repo.get_or_create_conversation.assert_awaited_once_with(org_id, 1)

    res_idem = await wa_repo.check_idempotency(msg_id)
    assert res_idem is False
    wa_repo._msg_repo.check_idempotency.assert_awaited_once_with(msg_id, org_id=None)

    res_book = await wa_repo.check_booking_exists(org_id, "+39123", "2026-09-05")
    assert res_book is False
    wa_repo._booking_repo.check_booking_exists.assert_awaited_once_with(org_id, "+39123", "2026-09-05", target_time=None)

    res_cache = await wa_repo.faq_cache_lookup(org_id, "hash123")
    assert res_cache is None
    wa_repo._doc_repo.faq_cache_lookup.assert_awaited_once_with(org_id, "hash123")

    res_usage = await wa_repo.check_message_usage(org_id)
    assert res_usage["messages_used_this_period"] == 5
    wa_repo._billing_repo.check_message_usage.assert_awaited_once_with(org_id)
