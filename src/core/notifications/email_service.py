import os
import smtplib
import asyncio
from email.message import EmailMessage
from src.core.db.repository import CoreRepository


def _get_smtp_config() -> dict:
    return {
        "host": os.environ["SMTP_HOST"],
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ["SMTP_USER"],
        "password": os.environ["SMTP_PASSWORD"],
        "from_addr": os.environ["SMTP_FROM"],
    }


async def send_escalation_notification(
    org_id: str,
    conversation_id: str,
    contact_name: str,
    pool,
) -> None:
    repo = CoreRepository(pool)
    owners = await repo.get_organization_owners(org_id)
    if not owners:
        return

    config = _get_smtp_config()
    msg = EmailMessage()
    msg["Subject"] = f"New escalation: {contact_name}"
    msg["From"] = config["from_addr"]
    msg["To"] = ", ".join(o["email"] for o in owners)
    msg.set_content(
        f"The conversation with {contact_name} has been escalated and is waiting for staff.\n\n"
        f"Conversation ID: {conversation_id}\n"
        f"Open the inbox to claim this ticket."
    )

    loop = asyncio.get_running_loop()

    def _send():
        with smtplib.SMTP(config["host"], config["port"], timeout=10) as server:
            server.starttls()
            server.login(config["user"], config["password"])
            server.send_message(msg)

    await loop.run_in_executor(None, _send)
