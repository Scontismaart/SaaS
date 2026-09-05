"""Repository decomposti per dominio del data layer."""
from src.core.db.repositories.billing_repo import BillingRepository
from src.core.db.repositories.booking_repo import BookingRepository
from src.core.db.repositories.contact_repo import ContactRepository
from src.core.db.repositories.conversation_repo import ConversationRepository
from src.core.db.repositories.document_repo import DocumentRepository
from src.core.db.repositories.message_repo import MessageRepository
from src.core.db.repositories.organization_repo import OrganizationRepository
from src.core.db.repositories.review_repo import ReviewRepository

__all__ = [
    "BillingRepository",
    "BookingRepository",
    "ContactRepository",
    "ConversationRepository",
    "DocumentRepository",
    "MessageRepository",
    "OrganizationRepository",
    "ReviewRepository",
]
