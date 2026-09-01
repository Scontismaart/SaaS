import pytest

import src.api.main as api_main


class FakeRepo:
    def __init__(self, billing):
        self._billing = billing

    async def get_organization_billing(self, org_id):
        if self._billing is None:
            raise ValueError("org inesistente")
        return self._billing


@pytest.mark.asyncio
async def test_blocca_rag_su_piano_starter():
    repo = FakeRepo({"plan": "starter", "subscription_status": "active"})
    msg = await api_main._piano_blocca_feature(repo, "org-1", "rag")
    assert msg and "Knowledge Base" in msg


@pytest.mark.asyncio
async def test_consentire_rag_su_business():
    repo = FakeRepo({"plan": "business", "subscription_status": "active"})
    assert await api_main._piano_blocca_feature(repo, "org-1", "rag") is None


@pytest.mark.asyncio
async def test_blocca_recensioni_su_starter_non_su_pro():
    repo = FakeRepo({"plan": "starter", "subscription_status": "active"})
    assert (await api_main._piano_blocca_feature(repo, "org-1", "recensioni")) is not None
    repo2 = FakeRepo({"plan": "pro", "subscription_status": "active"})
    assert await api_main._piano_blocca_feature(repo2, "org-1", "recensioni") is None


@pytest.mark.asyncio
async def test_trial_senza_piano_accesso_completo():
    repo = FakeRepo({"plan": None, "subscription_status": "trialing"})
    assert await api_main._piano_blocca_feature(repo, "org-1", "rag") is None


@pytest.mark.asyncio
async def test_billing_assente_consentire_failopen():
    repo = FakeRepo(None)
    assert await api_main._piano_blocca_feature(repo, "org-1", "rag") is None
