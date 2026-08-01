from datetime import datetime, timedelta
import logging

from src.models.schemas import (
    DisponibilitaSlot,
    PrenotazioneCalendario,
    PrenotazioneManualeInput,
)

logger = logging.getLogger(__name__)

# Fallback per demo mode (senza DB)
_prenotazioni_demo: list[PrenotazioneCalendario] = []
_coperti_massimi_per_slot = 40
_fasce_orarie = [f"{ora:02d}:00" for ora in range(24)]
_capienze_orarie = {ora: _coperti_massimi_per_slot for ora in _fasce_orarie}


def get_impostazioni_disponibilita() -> dict:
    return {
        "coperti_massimi_per_slot": _coperti_massimi_per_slot,
        "fasce_orarie": _fasce_orarie,
        "capienze_orarie": _capienze_orarie,
    }


def aggiorna_impostazioni_disponibilita(
    capienze_orarie: dict[str, int] | None = None,
    coperti_massimi_per_slot: int = 40,
    fasce_orarie: list[str] | None = None,
) -> dict:
    global _coperti_massimi_per_slot, _fasce_orarie, _capienze_orarie
    valori = capienze_orarie or {}
    if not capienze_orarie and fasce_orarie:
        valori = {fascia: coperti_massimi_per_slot for fascia in fasce_orarie}
    _coperti_massimi_per_slot = max(coperti_massimi_per_slot, 0)
    _fasce_orarie = [f"{ora:02d}:00" for ora in range(24)]
    _capienze_orarie = {
        ora: max(int(valori.get(ora, _coperti_massimi_per_slot)), 0)
        for ora in _fasce_orarie
    }
    return get_impostazioni_disponibilita()


def elenco_prenotazioni() -> list[PrenotazioneCalendario]:
    return list(_prenotazioni_demo)


def _ora_slot(ora: str) -> str:
    try:
        return f"{int(ora[:2]):02d}:00"
    except (TypeError, ValueError):
        return ora


def _coperti_prenotati(data: str, ora: str) -> int:
    fascia = _ora_slot(ora)
    return sum(
        p.coperti or 0 for p in _prenotazioni_demo
        if p.data == data and _ora_slot(p.ora) == fascia
        and p.stato.lower() not in {"cancellato", "annullato"}
    )


def _stato_slot(coperti_liberi: int, coperti_massimi: int) -> str:
    if coperti_liberi <= 0:
        return "rosso"
    if coperti_liberi <= max(4, round(coperti_massimi * 0.2)):
        return "giallo"
    return "verde"


def verifica_disponibilita(
    data: str,
    ora: str,
    coperti: int | None = None,
) -> DisponibilitaSlot:
    prenotati = _coperti_prenotati(data, ora)
    fascia_richiesta = _ora_slot(ora)
    massimi = _capienze_orarie.get(fascia_richiesta, _coperti_massimi_per_slot)
    liberi = max(massimi - prenotati, 0)
    alternative = []
    if coperti and coperti > liberi:
        alternative = [
            fascia for fascia in _fasce_orarie
            if fascia != fascia_richiesta
            and (_capienze_orarie.get(fascia, 0) - _coperti_prenotati(data, fascia)) >= coperti
        ][:2]
    return DisponibilitaSlot(
        data=data, ora=ora,
        coperti_massimi=massimi, coperti_prenotati=prenotati,
        coperti_liberi=liberi, stato=_stato_slot(liberi, massimi),
        alternative=alternative,
    )


def crea_prenotazione_dashboard(prenotazione: PrenotazioneManualeInput) -> PrenotazioneCalendario:
    creata = PrenotazioneCalendario(
        id=f"demo-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        nome_cliente=prenotazione.nome_cliente,
        telefono=prenotazione.telefono,
        data=prenotazione.data,
        ora=prenotazione.ora,
        coperti=prenotazione.coperti,
        note=prenotazione.note,
        stato=prenotazione.stato,
        origine=prenotazione.origine,
    )
    _prenotazioni_demo.append(creata)
    return creata


def semaforo_giorno(data: str | None = None) -> list[DisponibilitaSlot]:
    data = data or datetime.now().strftime("%Y-%m-%d")
    return [
        verifica_disponibilita(data, fascia)
        for fascia in _fasce_orarie
        if _capienze_orarie.get(fascia, 0) > 0
    ]


def prossimi_giorni_semaforo(giorni: int = 7) -> list[DisponibilitaSlot]:
    oggi = datetime.now().date()
    slots = []
    for offset in range(giorni):
        giorno = (oggi + timedelta(days=offset)).strftime("%Y-%m-%d")
        slots.extend(semaforo_giorno(giorno))
    return slots
