import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.whatsapp.config import AppConfig
from src.whatsapp.inbound_processor import InboundProcessor
from src.core.inbound.service import InboundProcessingService
from src.core.workers.inbound_worker import InboundWorker


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test-secret",
        encryption_key="MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
        postgres_dsn="postgresql://test:test@localhost:5432/test",
        verify_token="test-token",
        use_conversation_orchestrator=False,
    )


@pytest.fixture
def mock_deps():
    return {
        "repo": AsyncMock(),
        "service": AsyncMock(),
        "booking_service": AsyncMock(),
        "orchestrator": AsyncMock(),
    }


def test_inbound_processor_facade_composition(app_config, mock_deps):
    """Verifies InboundProcessor initializes InboundProcessingService and InboundWorker."""
    processor = InboundProcessor(
        app_config=app_config,
        repo=mock_deps["repo"],
        service=mock_deps["service"],
        booking_service=mock_deps["booking_service"],
        orchestrator=mock_deps["orchestrator"],
    )

    assert isinstance(processor.inbound_service, InboundProcessingService)
    assert isinstance(processor.worker, InboundWorker)
    assert processor.use_orchestrator is False


@pytest.mark.asyncio
async def test_inbound_processor_facade_delegates_process_one(app_config, mock_deps):
    """Verifies _process_one delegates to inbound_service.process_message."""
    processor = InboundProcessor(
        app_config=app_config,
        repo=mock_deps["repo"],
        service=mock_deps["service"],
        booking_service=mock_deps["booking_service"],
        orchestrator=mock_deps["orchestrator"],
    )

    processor.inbound_service.process_message = AsyncMock(return_value=None)
    fake_msg = {"id": uuid.uuid4(), "organization_id": uuid.uuid4()}

    await processor._process_one(fake_msg)
    processor.inbound_service.process_message.assert_awaited_once_with(fake_msg)


@pytest.mark.asyncio
async def test_inbound_processor_facade_mock_interception(app_config, mock_deps):
    """Verifies that patching _send_ai_reply or _finalize_message on the processor
    is properly intercepted when inbound_service calls its registered callbacks.
    """
    processor = InboundProcessor(
        app_config=app_config,
        repo=mock_deps["repo"],
        service=mock_deps["service"],
        booking_service=mock_deps["booking_service"],
        orchestrator=mock_deps["orchestrator"],
    )

    # When tests monkeypatch or patch.object processor._send_ai_reply:
    mock_send = AsyncMock(return_value={"wam_id": "test-wam-123"})
    processor._send_ai_reply = mock_send

    mock_finalize = AsyncMock(return_value=True)
    processor._finalize_message = mock_finalize

    # InboundProcessingService uses its bound lambdas:
    org_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    content = {"from": "+3912345678"}

    send_res = await processor.inbound_service._send_reply_fn(
        org_id, {"id": msg_id}, content, None, "Test reply"
    )
    assert send_res == {"wam_id": "test-wam-123"}
    mock_send.assert_awaited_once_with(
        org_id, {"id": msg_id}, content, None, "Test reply"
    )

    fin_res = await processor.inbound_service._finalize_fn(
        msg_id,
        handling_type="ai_handled",
        meta_message_id="test-wam-123",
        organization_id=org_id,
    )
    assert fin_res is True
    mock_finalize.assert_awaited_once_with(
        msg_id,
        handling_type="ai_handled",
        meta_message_id="test-wam-123",
        organization_id=org_id,
    )


@pytest.mark.asyncio
async def test_inbound_worker_polling_batch(app_config, mock_deps):
    """Verifies InboundWorker claims messages and processes each message."""
    mock_service = AsyncMock()
    worker = InboundWorker(
        repo=mock_deps["repo"],
        inbound_service=mock_service,
        batch_size=5,
    )

    fake_msg_1 = {"id": uuid.uuid4(), "organization_id": uuid.uuid4()}
    fake_msg_2 = {"id": uuid.uuid4(), "organization_id": uuid.uuid4()}
    mock_deps["repo"].claim_inbound_messages = AsyncMock(return_value=[fake_msg_1, fake_msg_2])

    await worker.process_next_batch()

    mock_deps["repo"].reap_stale_claims.assert_awaited_once()
    mock_deps["repo"].claim_inbound_messages.assert_awaited_once_with(limit=5)
    assert mock_service.process_message.await_count == 2
