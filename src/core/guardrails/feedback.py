"""
feedback.py
-----------
Feedback loop 👍/👎 sulle risposte AI (roadmap task 12): il log dei
feedback e' la materia prima per iterare sui prompt (join con
prompt_variant e intent nei usage_events).

Due sorgenti:
- cliente: un messaggio WhatsApp/Instagram che contiene SOLO un pollice
  (con eventuali varianti di tonalita' della pelle) viene interpretato
  come feedback sull'ultima risposta AI della conversazione;
- staff: pulsanti 👍/👎 nel thread dell'inbox (API POST).

Nota: le *reaction* WhatsApp/Instagram (evento webhook dedicato) non sono
ancora gestite dal webhook — MVP: solo messaggi di testo emoji-only.
"""

_THUMBS_UP = {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿"}
_THUMBS_DOWN = {"👎", "👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿"}


def rileva_feedback_emoji(testo: str) -> str | None:
    """'up'/'down' se il messaggio e' solo un pollice, altrimenti None.
    Un messaggio tipo 'grazie 👍' NON e' feedback: contiene altro testo e
    va gestito normalmente dal responder."""
    stripped = (testo or "").strip()
    if stripped in _THUMBS_UP:
        return "up"
    if stripped in _THUMBS_DOWN:
        return "down"
    return None
