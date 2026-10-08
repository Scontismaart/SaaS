from __future__ import annotations

import asyncio
import contextlib
import smtplib
from unittest.mock import AsyncMock, MagicMock

import pytest
from tenacity import wait_none

from src.core.notifications import email_service


def _exception(kind):
    if kind == "connect-4xx":
        return smtplib.SMTPConnectError(421, b"secret connect response")
    if kind == "sender-refused-4xx":
        return smtplib.SMTPSenderRefused(450, b"secret sender response", "owner@example.test")
    if kind == "data-4xx":
        return smtplib.SMTPDataError(451, b"secret data response")
    if kind == "data-5xx":
        return smtplib.SMTPDataError(550, b"secret permanent response")
    if kind == "disconnected":
        return smtplib.SMTPServerDisconnected("secret disconnect detail")
    if kind == "timeout":
        return TimeoutError("secret timeout detail")
    raise AssertionError(kind)


def _harness(monkeypatch, smtp_error):
    for key, value in {
        "SMTP_HOST": "smtp.invalid",
        "SMTP_PORT": "587",
        "SMTP_USER": "test-user",
        "SMTP_PASSWORD": "test-password",
        "SMTP_FROM": "noreply@example.test",
    }.items():
        monkeypatch.setenv(key, value)

    server = MagicMock()
    server_context = MagicMock()
    server_context.__enter__.return_value = server
    server.send_message.side_effect = smtp_error
    monkeypatch.setattr(email_service.smtplib, "SMTP", MagicMock(return_value=server_context))
    repository = MagicMock()
    repository.get_organization_owners = AsyncMock(return_value=[{"email": "owner@example.test"}])
    monkeypatch.setattr(email_service, "OrganizationRepository", MagicMock(return_value=repository))
    monkeypatch.setattr(email_service._send_with_retry.retry, "wait", wait_none())
    event = email_service.EmailEvent(
        org_id="synthetic-org",
        subject="PRIVATE SUBJECT SENTINEL",
        body="Private body",
        pool=object(),
    )
    return server, event


@pytest.mark.parametrize(
    ("kind", "expected_attempts"),
    [
        ("connect-4xx", 3),
        ("sender-refused-4xx", 3),
        ("data-4xx", 3),
        ("data-5xx", 1),
        ("disconnected", 1),
        ("timeout", 1),
    ],
)
@pytest.mark.asyncio
async def test_smtp_retries_only_definite_4xx_failures(monkeypatch, kind, expected_attempts):
    server, event = _harness(
        monkeypatch,
        [_exception(kind) for _ in range(expected_attempts)],
    )

    with pytest.raises(Exception):
        await email_service._send_with_retry(event)

    assert server.send_message.call_count == expected_attempts


@pytest.mark.asyncio
async def test_worker_logs_email_failure_type_without_subject_or_exception_text(
    monkeypatch, caplog
):
    caplog.set_level("CRITICAL")
    server, event = _harness(monkeypatch, _exception("disconnected"))
    queue = asyncio.Queue()
    monkeypatch.setattr(email_service, "_queue", queue)
    worker = asyncio.create_task(email_service._worker())
    try:
        await queue.put(event)
        await asyncio.wait_for(queue.join(), timeout=3)
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker

    assert server.send_message.call_count == 1
    assert any("SMTPServerDisconnected" in record.getMessage() or
               record.__dict__.get("error_type") == "SMTPServerDisconnected"
               for record in caplog.records)
    assert all("PRIVATE SUBJECT SENTINEL" not in record.getMessage() for record in caplog.records)
    assert all("secret disconnect detail" not in record.getMessage() for record in caplog.records)
