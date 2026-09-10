"""Gestione dell'identità cliente e delle email sintetiche RFC 2606.

Questo modulo centralizza la logica di rilevamento e generazione delle identità sintetiche
utilizzate per interoperare con provider esterni che richiedono obbligatoriamente un'email
(es. Cal.com) anche quando l'utente contatta il SaaS via WhatsApp senza aver fornito un'email.

Standard di riferimento:
- RFC 2606: TLD riservati (.invalid, .test, .example, .localhost) garantiti per non risolvere mai in rete.
- Dominio predefinito: `noemail.invalid`.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.bookings.ports.base import CustomerResult

DEFAULT_SYNTHETIC_DOMAIN = "noemail.invalid"

# Pattern noti di indirizzi email placeholder/sintetici
_SYNTHETIC_EMAIL_DOMAINS = (
    ".invalid",
    ".local",
    "wa.booking.local",
)
_SYNTHETIC_EMAIL_PREFIXES = (
    "guest_",
    "wa_",
)


def is_synthetic_email(email: str | None, custom_domain: str | None = None) -> bool:
    """Verifica se un indirizzo email è un placeholder generato dal sistema.

    Ritorna True se l'email termina con un dominio riservato (es. .invalid)
    o inizia con i prefissi sentinella noti (guest_, wa_).
    """
    if not email or not isinstance(email, str):
        return False

    e_low = email.strip().lower()

    if custom_domain:
        cd = custom_domain.strip().lower().lstrip("@")
        if e_low.endswith(f"@{cd}"):
            return True

    for dom in _SYNTHETIC_EMAIL_DOMAINS:
        if e_low.endswith(dom):
            return True

    user_part = e_low.split("@")[0] if "@" in e_low else e_low
    for pref in _SYNTHETIC_EMAIL_PREFIXES:
        if user_part.startswith(pref):
            return True

    return False


def generate_synthetic_email(customer: CustomerResult, domain: str = DEFAULT_SYNTHETIC_DOMAIN) -> str:
    """Genera un indirizzo email sintetico deterministico e RFC 2606 compliant.

    Utilizza il numero di telefono normalizzato per garantire l'idempotenza
    (stesso cliente -> stesso placeholder). Se il telefono non è presente,
    ripiega su customer_id.
    """
    clean_domain = domain.strip().lower().lstrip("@")
    raw_identifier = (customer.telefono or "").strip()
    digits_only = re.sub(r"[^\d]", "", raw_identifier)

    if digits_only:
        identifier = digits_only
    elif customer.customer_id:
        identifier = re.sub(r"[^a-zA-Z0-9_]", "", customer.customer_id)
    else:
        identifier = "unknown"

    return f"wa_{identifier}@{clean_domain}"
