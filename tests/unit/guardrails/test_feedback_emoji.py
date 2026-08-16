"""Rilevamento feedback emoji 👍/👎 (task 12): solo messaggi che sono
esclusivamente un pollice (con skin tones)."""

from src.core.guardrails.feedback import rileva_feedback_emoji


def test_pollice_su():
    assert rileva_feedback_emoji("👍") == "up"


def test_pollice_su_con_tonalita():
    for emoji in ("👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿"):
        assert rileva_feedback_emoji(emoji) == "up"


def test_pollice_giu():
    assert rileva_feedback_emoji("👎") == "down"
    assert rileva_feedback_emoji("👎🏽") == "down"


def test_spazi_bianchi_ignorati():
    assert rileva_feedback_emoji("  👍  \n") == "up"


def test_testo_con_emoji_non_e_feedback():
    assert rileva_feedback_emoji("grazie 👍") is None
    assert rileva_feedback_emoji("👍 ma non sono d'accordo") is None


def test_testo_vuoto_o_altro():
    assert rileva_feedback_emoji("") is None
    assert rileva_feedback_emoji("ciao!") is None
    assert rileva_feedback_emoji(None) is None


def test_altre_emoji_ignorate():
    assert rileva_feedback_emoji("❤️") is None
    assert rileva_feedback_emoji("😀") is None
