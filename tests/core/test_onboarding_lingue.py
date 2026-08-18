"""Multilingua (task 14): persistenza lingue nel profilo onboarding.

Round-trip completo: salvataggio (onboarding_profiles + sync su
organizations.business_profile) e rilettura dal responder reale
(_profile_from_dict). Default ["it"]/"it" per i profili che non configurano
lingue (nessuna regressione sul comportamento pre-migration).
"""

import json

import pytest

from src.core import onboarding
from src.models.schemas import OnboardingProfileInput
from src.whatsapp.inbound_processor import _profile_from_dict


def _profile(**overrides):
    data = {
        "verticale": "parrucchiere",
        "nome_attivita": "Studio Capelli Nora",
        "orari": "Martedi-Sabato 09:00-19:00",
        "tono": "gentile, curato, pratico",
        "servizi": ["Taglio", "Colore", "Piega"],
        "regole_escalation": ["Correzioni colore complesse", "Reclami"],
    }
    data.update(overrides)
    return OnboardingProfileInput(**data)


[pytest.mark.asyncio]
async def test_save_e_get_con_lingue_personalizzate(repo, sample_org):
    saved = await onboarding.save_profile(
        sample_org["id"],
        _profile(lingue_supportate=["it", "en", "de"], lingua_default="de"),
        repo,
    )
    assert saved["lingue_supportate"] == ["it", "en", "de"]
    assert saved["lingua_default"] == "de"

    fetched = await onboarding.get_profile(sample_org["id"], repo)
    assert fetched["lingue_supportate"] == ["it", "en", "de"]
    assert fetched["lingua_default"] == "de"
    # il profilo JSONB sincronizzato porta le stesse lingue
    assert fetched["profilo"]["lingue_supportate"] == ["it", "en", "de"]


[pytest.mark.asyncio]
async def test_default_italiano_senza_lingue(repo, sample_org):
    saved = await onboarding.save_profile(sample_org["id"], _profile(), repo)
    assert saved["lingue_supportate"] == ["it"]
    assert saved["lingua_default"] == "it"


[pytest.mark.asyncio]
async def test_sync_business_profile_round_trip_con_lingue(repo, sample_org):
    """Il JSON su organizations.business_profile deve portare anche le lingue:
    _profile_from_dict (responder reale) deve rileggerle 1:1."""
    payload = _profile(lingue_supportate=["it", "fr"], lingua_default="fr")
    await onboarding.save_profile(sample_org["id"], payload, repo)

    async with repo.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT business_profile FROM organizations WHERE id = $1",
            sample_org["id"],
        )
        raw = json.loads(row["business_profile"])

    riletto = _profile_from_dict(raw)
    assert riletto.lingue_supportate == ["it", "fr"]
    assert riletto.lingua_default == "fr"
    assert riletto.verticale == "parrucchiere"


[pytest.mark.asyncio]
async def test_profile_from_dict_default_italiano_senza_lingue():
    riletto = _profile_from_dict(
        {"nome": "X", "tipo_attivita": "ristorante", "tono": "t", "orari": "9-18"}
    )
    assert riletto.lingue_supportate == ["it"]
    assert riletto.lingua_default == "it"
    assert riletto.verticale is None


[pytest.mark.asyncio]
async def test_profile_from_dict_carica_verticale_e_lingue():
    riletto = _profile_from_dict(
        {
            "nome": "X",
            "lingue_supportate": ["it", "en"],
            "lingua_default": "en",
            "verticale": "studio_medico_dentista",
        }
    )
    assert riletto.lingue_supportate == ["it", "en"]
    assert riletto.lingua_default == "en"
    assert riletto.verticale == "studio_medico_dentista"