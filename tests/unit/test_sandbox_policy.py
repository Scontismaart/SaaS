import pytest
from src.core.channels.sandbox_policy import assert_recipient_allowed


@pytest.mark.parametrize("channel", ["whatsapp", "instagram"])
def test_default_denies_external_recipients(monkeypatch, channel):
    monkeypatch.delenv("SANDBOX_ONLY", raising=False)
    monkeypatch.delenv(f"{channel.upper()}_TEST_RECIPIENTS", raising=False)
    with pytest.raises(ValueError, match="non autorizzato"):
        assert_recipient_allowed(channel, "39000000000")


def test_explicit_sandbox_list_does_not_authorize_third_party(monkeypatch):
    monkeypatch.setenv("SANDBOX_ONLY", "true")
    monkeypatch.setenv("WHATSAPP_TEST_RECIPIENTS", "+39000000000")
    assert_recipient_allowed("whatsapp", "39000000000")
    with pytest.raises(ValueError):
        assert_recipient_allowed("whatsapp", "39000000001")
    with pytest.raises(ValueError):
        assert_recipient_allowed("whatsapp", "")


def test_invalid_policy_is_not_live_opt_in(monkeypatch):
    monkeypatch.setenv("SANDBOX_ONLY", "treu")
    with pytest.raises(ValueError, match="non valido"):
        assert_recipient_allowed("whatsapp", "39000000000")
