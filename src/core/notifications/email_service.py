import os
import smtplib
import asyncio
import logging
from dataclasses import dataclass
from email.message import EmailMessage
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError

from src.core.db.repository import CoreRepository


logger = logging.getLogger(__name__)

_queue: asyncio.Queue | None = None
_worker_task: asyncio.Task | None = None


@dataclass
class EmailEvent:
    org_id: str
    subject: str
    body: str
    pool: object  # asyncpg pool


def _get_smtp_config() -> dict | None:
    required = ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"]
    if any(not os.environ.get(key, "") for key in required):
        logger.warning("smtp=config_missing — notifica email non inviata, impostare SMTP_*")
        return None
    return {
        "host": os.environ["SMTP_HOST"],
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ["SMTP_USER"],
        "password": os.environ["SMTP_PASSWORD"],
        "from_addr": os.environ["SMTP_FROM"],
    }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=5, min=5, max=120),
    reraise=True,
)
async def _send_with_retry(event: EmailEvent) -> None:
    repo = CoreRepository(event.pool)
    owners = await repo.get_organization_owners(event.org_id)
    if not owners:
        return

    config = _get_smtp_config()
    if not config:
        return
    msg = EmailMessage()
    msg["Subject"] = event.subject
    msg["From"] = config["from_addr"]
    msg["To"] = ", ".join(o["email"] for o in owners)
    msg.set_content(event.body)

    loop = asyncio.get_running_loop()

    def _send():
        with smtplib.SMTP(config["host"], config["port"], timeout=10) as server:
            server.starttls()
            server.login(config["user"], config["password"])
            server.send_message(msg)

    await loop.run_in_executor(None, _send)


async def _worker():
    while True:
        event = await _queue.get()
        try:
            await _send_with_retry(event)
        except RetryError:
            logger.critical(
                "Email permanently failed after all retries",
                extra={
                    "org_id": event.org_id,
                    "subject": event.subject,
                },
            )
        except Exception as e:
            logger.critical(
                "Email failed with unexpected error",
                extra={
                    "org_id": event.org_id,
                    "subject": event.subject,
                    "error": str(e),
                },
            )
        finally:
            _queue.task_done()


def _enqueue(event: EmailEvent) -> None:
    if _queue is None:
        logger.error("Email queue not started — event dropped")
        return
    _queue.put_nowait(event)


def enqueue_escalation(
    org_id: str,
    conversation_id: str,
    contact_name: str,
    pool,
) -> None:
    _enqueue(EmailEvent(
        org_id=org_id,
        subject=f"New escalation: {contact_name}",
        body=(
            f"The conversation with {contact_name} has been escalated "
            f"and is waiting for staff.\n\n"
            f"Conversation ID: {conversation_id}\n"
            f"Open the inbox to claim this ticket."
        ),
        pool=pool,
    ))


SUSPENSION_NOTICE_SUBJECT = "Melpis — servizio sospeso"
SUSPENSION_NOTICE_BODY = (
    "Il tuo abbonamento a Melpis e' sospeso.\n\n"
    "Da questo momento il risponditore automatico non risponde piu' ai tuoi "
    "clienti su WhatsApp e le prenotazioni via WhatsApp sono sospese.\n"
    "Le prenotazioni gia' confermate restano valide.\n\n"
    "Rinnova il tuo abbonamento per riattivare il servizio."
)


def enqueue_suspension_notice(org_id: str, pool) -> None:
    _enqueue(EmailEvent(
        org_id=org_id,
        subject=SUSPENSION_NOTICE_SUBJECT,
        body=SUSPENSION_NOTICE_BODY,
        pool=pool,
    ))


def start_worker():
    global _queue, _worker_task
    if _worker_task is not None:
        return
    _queue = asyncio.Queue()
    _worker_task = asyncio.ensure_future(_worker())


def stop_worker():
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        _worker_task = None
