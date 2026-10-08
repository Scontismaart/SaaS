import importlib

import pytest


@pytest.mark.parametrize("confirmation", [None, "false", "TRUE", "1", "true"])
def test_generic_credentials_never_enable_live_airtable(monkeypatch, confirmation):
    for key in ("AIRTABLE_SANDBOX_TOKEN", "AIRTABLE_SANDBOX_BASE_ID", "AIRTABLE_SANDBOX_CONFIRMED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AIRTABLE_PAT", "synthetic-general-token")
    monkeypatch.setenv("AIRTABLE_TOKEN", "synthetic-general-token")
    monkeypatch.setenv("AIRTABLE_BASE_ID", "synthetic-general-base")
    if confirmation:
        monkeypatch.setenv("AIRTABLE_SANDBOX_CONFIRMED", confirmation)
    from tests.integrations.airtable import test_airtable_live_sandbox as live
    importlib.reload(live)
    assert live.SANDBOX_TOKEN is None
    assert live.SANDBOX_BASE_ID is None
    assert not live.sandbox_confirmed()


@pytest.mark.parametrize("confirmation,expected", [(None, False), ("false", False), ("true", True)])
def test_dedicated_sandbox_also_requires_explicit_confirmation(monkeypatch, confirmation, expected):
    from tests.integrations.airtable import test_airtable_live_sandbox as live
    monkeypatch.setattr(live, "SANDBOX_TOKEN", "synthetic-sandbox-token")
    monkeypatch.setattr(live, "SANDBOX_BASE_ID", "synthetic-sandbox-base")
    monkeypatch.delenv("AIRTABLE_SANDBOX_CONFIRMED", raising=False)
    if confirmation:
        monkeypatch.setenv("AIRTABLE_SANDBOX_CONFIRMED", confirmation)
    assert live.sandbox_confirmed() is expected
