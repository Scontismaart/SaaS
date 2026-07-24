from __future__ import annotations

import base64
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from src.core.email_sources.base import EmailInput
from src.core.email_config_store import carica_config
from src.core.gmail_token_store import get_service


def _html_a_testo(html: str) -> str:
    testo = re.sub(r"<[^>]+>", " ", html)
    testo = re.sub(r"\s+", " ", testo)
    return testo.strip()


def _estrai_corpo_da_payload(payload: dict) -> str:
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for part in payload["parts"]:
            if part["mimeType"] == "text/html":
                data = part["body"].get("data", "")
                if data:
                    raw = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    return _html_a_testo(raw)
    else:
        data = payload["body"].get("data", "")
        if data:
            raw = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if payload.get("mimeType", "").startswith("text/html"):
                return _html_a_testo(raw)
            return raw
    return ""


def _header_value(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h.get("value", "")
    return ""


def recupera_nuove_email(indirizzo_forzato: str | None = None) -> list[EmailInput]:
    if indirizzo_forzato:
        configs = carica_config(indirizzo_forzato)
    else:
        configs = carica_config()

    if not configs:
        return []

    risultati: list[EmailInput] = []
    for cfg in configs:
        indirizzo = cfg["indirizzo"]
        try:
            service = get_service(indirizzo)
        except ValueError:
            continue

        try:
            response = service.users().messages().list(
                userId="me",
                q="is:inbox is:unread",
                maxResults=50,
            ).execute()
        except Exception:
            continue

        msg_ids = response.get("messages", [])
        if not msg_ids:
            continue

        for msg_data in msg_ids:
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_data["id"], format="full"
                ).execute()
            except Exception:
                continue

            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            mittente = _header_value(headers, "From")
            oggetto = _header_value(headers, "Subject")
            date_str = _header_value(headers, "Date")
            ricevuta = parsedate_to_datetime(date_str) if date_str else datetime.now()
            corpo = _estrai_corpo_da_payload(payload)

            risultati.append(
                EmailInput(
                    mittente=mittente,
                    oggetto=oggetto,
                    corpo_testo=corpo,
                    allegati=[],
                    ricevuta_il=ricevuta,
                )
            )

            try:
                service.users().messages().modify(
                    userId="me", id=msg_data["id"],
                    body={"removeLabelIds": ["UNREAD"]},
                ).execute()
            except Exception:
                pass

        print(f"[gmail_api] Scaricate {len(msg_ids)} email da {indirizzo}.")

    return risultati
