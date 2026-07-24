import os
import sys
import json
import base64
import re
import time

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_PROGRESS_DIR = os.path.join(_project_root, "data", "reindex_progress")


def _progress_file(tid: str) -> str:
    return os.path.join(_PROGRESS_DIR, f"{tid}.json")


def _save(tid: str, data: dict):
    os.makedirs(_PROGRESS_DIR, exist_ok=True)
    with open(_progress_file(tid), "w") as f:
        json.dump(data, f)


def _html_a_testo(html: str) -> str:
    testo = re.sub(r"<[^>]+>", " ", html)
    testo = re.sub(r"\s+", " ", testo)
    return testo.strip()


def _decodifica_b64(data: str) -> str:
    # Il padding base64url a volte manca nei payload Gmail: lo normalizziamo
    # per evitare crash di binascii.Error su email con codifiche particolari.
    data = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def _testo_da_parte(parte: dict) -> str:
    body = parte.get("body") or {}
    data = body.get("data", "")
    if not data:
        return ""
    try:
        return _decodifica_b64(data)
    except Exception:
        return ""


def _cerca_mime_ricorsivo(payload: dict, mime_target: str) -> str:
    """Cerca ricorsivamente in tutte le parti annidate (multipart/mixed che
    contiene multipart/alternative che contiene multipart/related, ecc.)
    una parte con il mimeType richiesto. Le email reali hanno spesso più
    livelli di annidamento: guardare solo il primo livello (come prima)
    fa perdere il corpo di molte email."""
    if not payload:
        return ""
    if payload.get("mimeType") == mime_target:
        testo = _testo_da_parte(payload)
        if testo:
            return testo
    for sotto_parte in payload.get("parts") or []:
        trovato = _cerca_mime_ricorsivo(sotto_parte, mime_target)
        if trovato:
            return trovato
    return ""


def _estrai_corpo_da_payload(payload: dict) -> str:
    """Estrae il corpo testuale di un'email in modo difensivo: alcune email
    (bozze, messaggi di chat, notifiche automatiche) hanno un payload senza
    la chiave 'body' o senza 'parts', e l'accesso diretto payload["body"]
    faceva crashare l'intera re-indicizzazione con un KeyError non gestito."""
    if not payload:
        return ""

    testo_plain = _cerca_mime_ricorsivo(payload, "text/plain")
    if testo_plain:
        return testo_plain

    testo_html = _cerca_mime_ricorsivo(payload, "text/html")
    if testo_html:
        return _html_a_testo(testo_html)

    # fallback: payload senza 'parts' e senza mimeType riconosciuto,
    # proviamo comunque a leggere un eventuale body diretto
    if not payload.get("parts"):
        testo = _testo_da_parte(payload)
        if testo:
            if payload.get("mimeType", "").startswith("text/html"):
                return _html_a_testo(testo)
            return testo

    return ""


def _header_value(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h.get("value", "")
    return ""


def run_reindex(tid: str):
    from src.core.documenti.vector_store import resetta, aggiungi
    from src.core.documenti.chunking import chunk_testo
    from src.core.documenti.embeddings import vettorizza
    from src.core.gmail_token_store import get_service
    from src.core.email_config_store import carica_config

    try:
        _save(tid, {"status": "processing", "progress": "Caricamento modello AI..."})
        vettorizza(["warmup"])
        configs = carica_config()
        if not configs:
            _save(tid, {"status": "error", "errore": "Nessun account Gmail configurato."})
            return

        resetta()
        tutti_chunk: list[str] = []
        tutti_metadati: list[dict] = []
        totale_scaricati = 0
        totale_vuoti = 0

        for cfg in configs:
            indirizzo = cfg["indirizzo"]
            _save(tid, {"status": "processing", "progress": f"Connessione a {indirizzo}..."})

            try:
                service = get_service(indirizzo)
            except ValueError:
                _save(tid, {"status": "error", "errore": f"Gmail non autorizzato per {indirizzo}."})
                return

            messaggi: list[dict] = []
            response = service.users().messages().list(userId="me", maxResults=500).execute()
            messaggi.extend(response.get("messages", []))
            while "nextPageToken" in response:
                response = service.users().messages().list(
                    userId="me", pageToken=response["nextPageToken"], maxResults=500
                ).execute()
                messaggi.extend(response.get("messages", []))

            totale = len(messaggi)
            if totale == 0:
                continue

            for i, msg_data in enumerate(messaggi):
                _save(tid, {"status": "processing", "progress": f"[{indirizzo}] Scarico {i+1}/{totale}...", "chunk": len(tutti_chunk)})

                try:
                    msg = service.users().messages().get(userId="me", id=msg_data["id"], format="full").execute()
                except Exception:
                    continue

                payload = msg.get("payload", {})
                headers = payload.get("headers", [])
                oggetto = _header_value(headers, "Subject")
                corpo = _estrai_corpo_da_payload(payload)

                if not corpo:
                    totale_vuoti += 1
                    continue

                chunks = chunk_testo(corpo)
                if not chunks:
                    totale_vuoti += 1
                    continue

                fonte = oggetto or f"Email #{msg_data['id']}"
                tutti_chunk.extend(chunks)
                tutti_metadati.extend([{"fonte": fonte, "tipo": "email"}] * len(chunks))
                totale_scaricati += 1

        if tutti_chunk:
            _save(tid, {"status": "processing", "progress": f"Indicizzazione di {len(tutti_chunk)} chunk in batch..."})

            def _progress(cur: int, tot: int):
                pct = int(cur / tot * 100)
                _save(tid, {"status": "processing", "progress": f"Indicizzazione {cur}/{tot} ({pct}%)...", "chunk": cur})

            aggiunti = aggiungi(tutti_chunk, tutti_metadati, on_progress=_progress)
            _save(tid, {"status": "done", "progress": f"Completato. {aggiunti} chunk indicizzati da {totale_scaricati} email ({totale_vuoti} vuote saltate).", "chunk": aggiunti, "risultato": {"chunk_indicizzati": aggiunti, "email_processate": totale_scaricati, "email_saltate": totale_vuoti}})
        else:
            _save(tid, {"status": "done", "progress": "Nessuna email con corpo testo trovata.", "chunk": 0, "risultato": {"chunk_indicizzati": 0}})

    except Exception:
        import traceback
        traceback.print_exc()
        _save(tid, {"status": "error", "errore": traceback.format_exc()})
