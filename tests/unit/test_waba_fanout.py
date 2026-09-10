"""Regression P0 waba_id: lookup ambiguo non deve mai scrivere nel tenant errato.

Scenario: Tenant A + Tenant B condividono lo stesso waba_id (1:N legittimo per
realta' Meta: un WABA contiene N numeri), Tenant C ha un waba_id diverso.
L'evento template-status (a livello WABA, senza phone_number_id) deve aggiornare
A e B (verita' upstream condivisa) e MAI toccare C; con waba unico il comportamento
resta quello storico (una sola org aggiornata); waba ignoto/mancante = no-op.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.whatsapp.router import _handle_template_status_update

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
ORG_C = uuid.uuid4()
SHARED_WABA = "waba_shared_001"
OTHER_WABA = "waba_other_002"
UNKNOWN_WABA = "waba_unknown_999"


class StrictFakeRepo:
    """Fake con semantica reale: righe account 1:N su waba_id, template per-org,
    update_template_status scoped SOLO su (organization_id, name, language)."""

    def __init__(self):
        self.accounts = [
            {"organization_id": ORG_A, "waba_id": SHARED_WABA},
            {"organization_id": ORG_B, "waba_id": SHARED_WABA},
            {"organization_id": ORG_C, "waba_id": OTHER_WABA},
        ]
        self.templates = {
            (ORG_A, "promo_welcome", "it"): "PENDING",
            (ORG_B, "promo_welcome", "it"): "PENDING",
            (ORG_C, "promo_welcome", "it"): "PENDING",
        }
        self.writes: list[tuple] = []

    async def get_orgs_by_waba_id(self, waba_id: str) -> list:
        return sorted(
            ({"organization_id": a["organization_id"], "waba_id": a["waba_id"]}
             for a in self.accounts if a["waba_id"] == waba_id),
            key=lambda d: str(d["organization_id"]),
        )

    async def get_org_by_waba_id(self, waba_id: str):
        orgs = await self.get_orgs_by_waba_id(waba_id)
        return orgs[0] if orgs else None

    async def update_template_status(self, organization_id, name, language, status,
                                     rejected_reason=None):
        # Scoped write reale: tocca SOLO la riga della propria org.
        key = (organization_id, name, language)
        assert key in self.templates, f"cross-tenant write tentata su {key}"
        self.templates[key] = status
        self.writes.append((organization_id, name, language, status))


def _value(status="APPROVED"):
    return SimpleNamespace(
        message_template_name="promo_welcome",
        message_template_language="it",
        message_template_status=status,
        reason=None,
    )


class TestWabaFanout:
    @pytest.mark.asyncio
    async def test_shared_waba_updates_both_orgs_never_other(self):
        repo = StrictFakeRepo()
        await _handle_template_status_update(repo, _value("APPROVED"), entry_id=SHARED_WABA)

        assert repo.templates[(ORG_A, "promo_welcome", "it")] == "APPROVED"
        assert repo.templates[(ORG_B, "promo_welcome", "it")] == "APPROVED"
        # Tenant C con altro waba MAI toccato
        assert repo.templates[(ORG_C, "promo_welcome", "it")] == "PENDING"
        # Ogni write porta l'org corretta: nessuna cross-tenant write
        written_orgs = {w[0] for w in repo.writes}
        assert written_orgs == {ORG_A, ORG_B}

    @pytest.mark.asyncio
    async def test_unique_waba_updates_single_org(self):
        repo = StrictFakeRepo()
        await _handle_template_status_update(repo, _value("REJECTED"), entry_id=OTHER_WABA)

        assert repo.templates[(ORG_C, "promo_welcome", "it")] == "REJECTED"
        assert repo.templates[(ORG_A, "promo_welcome", "it")] == "PENDING"
        assert repo.templates[(ORG_B, "promo_welcome", "it")] == "PENDING"
        assert repo.writes == [(ORG_C, "promo_welcome", "it", "REJECTED")]

    @pytest.mark.asyncio
    async def test_unknown_waba_no_write(self):
        repo = StrictFakeRepo()
        await _handle_template_status_update(repo, _value(), entry_id=UNKNOWN_WABA)

        assert repo.writes == []
        assert all(s == "PENDING" for s in repo.templates.values())

    @pytest.mark.asyncio
    async def test_missing_entry_id_no_write(self):
        repo = StrictFakeRepo()
        await _handle_template_status_update(repo, _value(), entry_id=None)

        assert repo.writes == []

    @pytest.mark.asyncio
    async def test_lookup_returns_all_matching_orgs_ordered(self):
        repo = StrictFakeRepo()
        orgs = await repo.get_orgs_by_waba_id(SHARED_WABA)

        assert [o["organization_id"] for o in orgs] == sorted(
            [ORG_A, ORG_B], key=str
        )
        assert await repo.get_orgs_by_waba_id(UNKNOWN_WABA) == []
