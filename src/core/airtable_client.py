import os
from pyairtable import Api
from src.models.schemas import DatiPrenotazione, PrenotazioneCalendario, RispostaOutput


def _get_table():
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    table_name = os.getenv("AIRTABLE_TABLE_NAME", "Prenotazioni")
    if not api_key or not base_id:
        return None
    api = Api(api_key)
    return api.table(base_id, table_name)


def _combina_data_ora(data: str, ora: str) -> str:
    """Combina data (YYYY-MM-DD) e ora (HH:MM) in ISO datetime UTC."""
    if data and ora:
        return f"{data}T{ora}:00.000Z"
    return ora or data


def salva_prenotazione(
    prenotazione: DatiPrenotazione,
    risposta: RispostaOutput,
    id_conversazione: str,
) -> dict | None:
    table = _get_table()
    if table is None:
        return None

    record = {
        "Nome cliente": prenotazione.nome_cliente,
        "Telefono": prenotazione.telefono,
        "Numero coperti": prenotazione.coperti,
        "Note": prenotazione.note,
        "Stato": "In attesa",
        "Origine": "WhatsApp",
        "ID conversazione": id_conversazione,
        "Richiesta umano": risposta.richiede_umano,
    }

    if prenotazione.data and prenotazione.ora:
        record["Ora prenotazione"] = _combina_data_ora(prenotazione.data, prenotazione.ora)
    elif prenotazione.data:
        record["Data prenotazione"] = prenotazione.data
    elif prenotazione.ora:
        record["Ora prenotazione"] = prenotazione.ora

    return table.create(record)


def crea_prenotazione_manuale(prenotazione: DatiPrenotazione, stato: str = "Confermato") -> dict | None:
    table = _get_table()
    if table is None:
        return None

    record = {
        "Nome cliente": prenotazione.nome_cliente,
        "Telefono": prenotazione.telefono,
        "Numero coperti": prenotazione.coperti,
        "Note": prenotazione.note,
        "Stato": stato,
        "Origine": "Dashboard",
        "Richiesta umano": False,
    }

    if prenotazione.data and prenotazione.ora:
        record["Ora prenotazione"] = _combina_data_ora(prenotazione.data, prenotazione.ora)
    elif prenotazione.data:
        record["Data prenotazione"] = prenotazione.data
    elif prenotazione.ora:
        record["Ora prenotazione"] = prenotazione.ora

    return table.create(record)


def _normalizza_prenotazione(record: dict) -> PrenotazioneCalendario:
    campi = record.get("fields", {})
    data = campi.get("Data prenotazione") or ""
    ora = ""

    ora_prenotazione = campi.get("Ora prenotazione") or ""
    if isinstance(ora_prenotazione, str) and "T" in ora_prenotazione:
        data = data or ora_prenotazione[:10]
        ora = ora_prenotazione[11:16]
    elif isinstance(ora_prenotazione, str):
        ora = ora_prenotazione[:5]

    return PrenotazioneCalendario(
        id=record.get("id", ""),
        nome_cliente=campi.get("Nome cliente", ""),
        telefono=campi.get("Telefono", ""),
        data=data,
        ora=ora,
        coperti=campi.get("Numero coperti"),
        note=campi.get("Note", ""),
        stato=campi.get("Stato", "In attesa"),
        origine=campi.get("Origine", "Airtable"),
        richiede_intervento=bool(campi.get("Richiesta umano", False)),
    )


def lista_prenotazioni() -> list[PrenotazioneCalendario]:
    table = _get_table()
    if table is None:
        return []

    records = table.all()
    return [_normalizza_prenotazione(r) for r in records]
