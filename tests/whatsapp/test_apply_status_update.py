import pytest
from src.whatsapp.repository import apply_status_update


class TestApplyStatusUpdate:
    def test_sent_to_delivered_allowed(self):
        assert apply_status_update("sent", "delivered") is True

    def test_delivered_to_read_allowed(self):
        assert apply_status_update("delivered", "read") is True

    def test_read_to_delivered_blocked(self):
        assert apply_status_update("read", "delivered") is False

    def test_failed_always_wins(self):
        assert apply_status_update("delivered", "failed") is True
        assert apply_status_update("sent", "failed") is True
        assert apply_status_update("read", "failed") is True

    def test_same_status_blocked(self):
        assert apply_status_update("delivered", "delivered") is False

    def test_queued_to_sent_allowed(self):
        assert apply_status_update("queued", "sent") is True

    def test_sending_ambiguous_to_sent_allowed(self):
        assert apply_status_update("sending_ambiguous", "sent") is True

    def test_sending_ambiguous_to_delivered_allowed(self):
        assert apply_status_update("sending_ambiguous", "delivered") is True
