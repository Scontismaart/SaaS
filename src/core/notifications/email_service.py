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
class EscalationEvent:
    org_id: str
    conversation_id: str
    contact_name: str
    pool: object  # asyncpg pool


def _get_smtp_config() -> dict:
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
async def _send_with_retry(event: EscalationEvent) -> None:
    repo = CoreRepository(event.pool)
    owners = await repo.get_organization_owners(event.org_id)
    if not owners:
        return

    config = _get_smtp_config()
    msg = EmailMessage()
    msg["Subject"] = f"New escalation: {event.contact_name}"
    msg["From"] = config["from_addr"]
    msg["To"] = ", ".join(o["email"] for o in owners)
    msg.set_content(
        f"The conversation with {event.contact_name} has been escalated "
        f"and is waiting for staff.\n\n"
        f"Conversation ID: {event.conversation_id}\n"
        f"Open the inbox to claim this ticket."
    )

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
                "Escalation email permanently failed after all retries",
                extra={
                    "org_id": event.org_id,
                    "conversation_id": event.conversation_id,
                    "contact_name": event.contact_name,
                },
            )
        except Exception as e:
            logger.critical(
                "Escalation email failed with unexpected error",
                extra={
                    "org_id": event.org_id,
                    "conversation_id": event.conversation_id,
                    "error": str(e),
                },
            )
        finally:
            _queue.task_done()


def enqueue_escalation(
    org_id: str,
    conversation_id: str,
    contact_name: str,
    pool,
) -> None:
    if _queue is None:
        logger.error("Escalation queue not started — event dropped")
        return
    _queue.put_nowait(EscalationEvent(
        org_id=org_id,
        conversation_id=conversation_id,
        contact_name=contact_name,
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
