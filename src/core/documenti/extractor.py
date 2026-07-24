import io
from pathlib import Path

from PIL import Image
from pypdf import PdfReader


ESTENSIONI_TESTO = {".txt", ".md", ".csv", ".json"}
ESTENSIONI_PDF = {".pdf"}
ESTENSIONI_IMMAGINE = {".png", ".jpg", ".jpeg", ".webp"}


def _ocr_immagine(immagine) -> str:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ValueError("OCR locale non installato. Esegui pip install -r requirements.txt.") from exc

    risultato, _ = RapidOCR()(immagine)
    testo = "\n".join(riga[1] for riga in (risultato or []) if len(riga) > 1 and riga[1])
    return testo.strip()


def _estrai_immagine(contenuto: bytes, nome: str) -> str:
    immagine = Image.open(io.BytesIO(contenuto)).convert("RGB")
    testo = _ocr_immagine(immagine)
    if not testo.strip():
        raise ValueError(f"Nessun testo leggibile trovato in {nome}.")
    return testo.strip()


def _estrai_pdf_scansionato(contenuto: bytes, nome: str) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise ValueError(f"Il PDF {nome} è scansionato. Installa il supporto PDF locale e riprova.") from exc

    testo_pagine = []
    documento = fitz.open(stream=contenuto, filetype="pdf")
    for pagina in documento:
        pixmap = pagina.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        testo = _ocr_immagine(Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB"))
        if testo:
            testo_pagine.append(testo)
    return "\n\n".join(testo_pagine).strip()


def estrai_testo(contenuto: bytes, nome: str, content_type: str = "") -> str:
    estensione = Path(nome).suffix.lower()
    if estensione in ESTENSIONI_TESTO or content_type.startswith("text/"):
        return contenuto.decode("utf-8-sig", errors="replace").strip()
    if estensione in ESTENSIONI_PDF or content_type == "application/pdf":
        reader = PdfReader(io.BytesIO(contenuto))
        testo = "\n\n".join((pagina.extract_text() or "").strip() for pagina in reader.pages)
        if not testo.strip():
            testo = _estrai_pdf_scansionato(contenuto, nome)
        if not testo.strip():
            raise ValueError(f"Nessun testo leggibile trovato in {nome}.")
        return testo.strip()
    if estensione in ESTENSIONI_IMMAGINE or content_type.startswith("image/"):
        return _estrai_immagine(contenuto, nome)
    raise ValueError("Formato non supportato. Usa TXT, MD, CSV, JSON, PDF, PNG, JPG o WEBP.")
