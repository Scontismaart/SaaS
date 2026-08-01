from src.core import onboarding
from src.models.schemas import OnboardingProfileInput, PreviewInput


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


def test_save_profile_sets_active_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "PROFILE_STORE", tmp_path / "profiles.json")

    record = onboarding.save_profile(_profile())
    active = onboarding.get_active_profile()

    assert record["verticale"] == "parrucchiere"
    assert active is not None
    assert active.nome == "Studio Capelli Nora"
    assert "Taglio" in active.servizi_principali


def test_preview_escalates_sensitive_vertical_request(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "PROFILE_STORE", tmp_path / "profiles.json")
    request = PreviewInput(
        profilo=_profile(
            verticale="studio_medico_dentista",
            nome_attivita="Studio Sorriso",
            servizi=["Igiene", "Visite"],
            regole_escalation=["Dolore acuto", "Farmaci"],
        ),
        messaggio="Ho dolore a un dente, cosa posso prendere?",
    )

    result = onboarding.generate_preview(request)

    assert result.richiede_umano is True
    assert result.categoria == "escalation"


def test_preview_answers_known_hours(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "PROFILE_STORE", tmp_path / "profiles.json")
    request = PreviewInput(
        profilo=_profile(
            verticale="hotel_bnb",
            nome_attivita="Casa Lido",
            orari="Check-in 15:00-20:00",
        ),
        messaggio="A che ora posso fare check-in?",
    )

    result = onboarding.generate_preview(request)

    assert result.richiede_umano is False
    assert "Check-in 15:00-20:00" in result.risposta
