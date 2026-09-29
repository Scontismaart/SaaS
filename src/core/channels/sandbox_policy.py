"""No external send is authorized by an arbitrary browser-supplied recipient."""
import os
import re


def assert_recipient_allowed(channel: str, recipient: str) -> None:
    policy = os.getenv("SANDBOX_ONLY", "true").strip().lower()
    if policy not in {"true", "false"}:
        raise ValueError("SANDBOX_ONLY non valido")
    if policy == "false":
        return
    if channel not in {"whatsapp", "instagram"}:
        raise ValueError("Canale sandbox non riconosciuto")

    def normalize(value):
        value = str(value).strip()
        if channel == "whatsapp":
            value = value.removeprefix("+")
        if not re.fullmatch(r"[0-9]{5,25}", value):
            return None
        return value

    target = normalize(recipient)
    allowed = {normalize(v) for v in os.getenv(f"{channel.upper()}_TEST_RECIPIENTS", "").split(",")}
    allowed.discard(None)
    if not target or target not in allowed:
        raise ValueError("Invio bloccato: destinatario non autorizzato nella sandbox")
