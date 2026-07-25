import logging

import pytest

from src.core.logging_filter import PIIWhitelistFilter, SAFE_KEYS


def _make_record(msg: str, *args) -> logging.LogRecord:
    logger = logging.getLogger("test")
    return logger.makeRecord(
        logger.name, logging.INFO, "test.py", 1, msg, args, None
    )


def test_filter_blocks_free_text():
    f = PIIWhitelistFilter()
    record = _make_record("Ciao Mario, il tuo tavolo e' pronto alle 20:00")
    assert f.filter(record) is False


def test_filter_blocks_phone_number():
    f = PIIWhitelistFilter()
    record = _make_record("from=%s", "+393401234567")
    assert f.filter(record) is False


def test_filter_blocks_email():
    f = PIIWhitelistFilter()
    record = _make_record("user=%s", "mario.rossi@gmail.com")
    assert f.filter(record) is False


def test_filter_allows_safe_metadata():
    f = PIIWhitelistFilter()
    record = _make_record("msg_id=%s org_id=%s status=%s", "msg_123", "org_456", "delivered")
    assert f.filter(record) is True


def test_filter_blocks_empty():
    f = PIIWhitelistFilter()
    record = _make_record("")
    assert f.filter(record) is False


def test_filter_blocks_message_body_in_args():
    f = PIIWhitelistFilter()
    record = _make_record("body=%s", "Ciao Mario, confermo il tavolo alle 20:00")
    assert f.filter(record) is False


def test_safe_keys_exists():
    assert "msg_id" in SAFE_KEYS
    assert "org_id" in SAFE_KEYS
    assert "status" in SAFE_KEYS
    assert len(SAFE_KEYS) >= 10
