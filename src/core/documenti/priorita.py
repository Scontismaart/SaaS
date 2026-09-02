"""
priorita.py
-----------
Definizione della gerarchia di priorità esplicita tra le fonti di conoscenza:
    Dati struttura (1) > FAQ (2) > Documenti (3) > Pagine web (4)

Include la logica di rilevamento conflitti tra fonti (es. prezzi discordanti).
"""

from __future__ import annotations

import re
from typing import Any

# Livello numerico di priorità (1 = massimo, 4 = minimo)
PRIORITA_TIPI: dict[str, int] = {
    "dati_struttura": 1,
    "faq": 2,
    "documento": 3,
    "upload": 3,
    "web": 4,
}

LABEL_PRIORITA: dict[str, str] = {
    "dati_struttura": "Dati struttura (Priorità 1 - Massima)",
    "faq": "FAQ (Priorità 2)",
    "documento": "Documento (Priorità 3)",
    "upload": "Documento (Priorità 3)",
    "web": "Pagina Web (Priorità 4)",
}

GERARCHIA_REGOLA_PROMPT = (
    "GERARCHIA DI PRIORITÀ TRA LE FONTI (RISOLUZIONE CONFLITTI):\n"
    "Le informazioni fornite rispettano questa rigida gerarchia:\n"
    "1. Dati struttura (Autorevoli e prevalenti: servizi, prezzi attuali, orari, operatori)\n"
    "2. FAQ (Risposte mirate e verificate)\n"
    "3. Documenti (PDF, listini e file caricati)\n"
    "4. Pagine web (Contenuti importati da URL)\n\n"
    "Se riscontri discrepanze o dati contrastanti tra due fonti (es. un prezzo o un orario diverso "
    "tra i Dati struttura e un Documento o una Pagina web), considera SEMPRE E SOLO come valida "
    "l'informazione della fonte con priorità più alta, ignorando il dato della fonte a priorità inferiore."
)


def get_priorita_num(tipo: str) -> int:
    return PRIORITA_TIPI.get(tipo.lower(), 5)


def formatta_chunk_con_priorita(chunk: dict[str, Any]) -> str:
    """Formatta un chunk per il prompt indicando esplicitamente tipo e priorità."""
    tipo = (chunk.get("metadata") or {}).get("tipo") or chunk.get("tipo") or "documento"
    nome = (
        chunk.get("document_name")
        or (chunk.get("metadata") or {}).get("fonte")
        or "documento"
    )
    priorita_label = LABEL_PRIORITA.get(tipo, "Documento")
    return f"-- [{priorita_label}] {nome} --\n{chunk['content']}"


def rileva_conflitti_prezzo(
    servizi_strutturati: list[dict[str, Any]],
    altre_fonti_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rileva eventuali discrepanze tra i prezzi nei Dati struttura (priorità 1)

    e i prezzi menzionati nelle altre fonti (FAQ, Documenti, Web).
    """
    conflitti = []
    if not servizi_strutturati or not altre_fonti_chunks:
        return conflitti

    # Pattern per estrarre importi
    prezzo_re = re.compile(
        r"€\s*(\d+(?:[.,]\d{1,2})?)|(\d+(?:[.,]\d{1,2})?)\s*(?:€|euro\b)",
        re.IGNORECASE,
    )

    for serv in servizi_strutturati:
        nome_servizio = serv.get("nome", "").strip()
        prezzo_ufficiale = serv.get("prezzo")
        if not nome_servizio or prezzo_ufficiale is None:
            continue

        try:
            prezzo_ufficiale_val = float(prezzo_ufficiale)
        except (ValueError, TypeError):
            continue

        parole_chiave = [p.lower() for p in nome_servizio.split() if len(p) > 2]
        if not parole_chiave:
            continue

        for chunk in altre_fonti_chunks:
            meta = chunk.get("metadata") or {}
            tipo_fonte = meta.get("tipo") or chunk.get("tipo") or "documento"
            if tipo_fonte == "dati_struttura":
                continue  # Confrontiamo solo con fonti diverse dai dati struttura

            testo = chunk.get("content", "")
            testo_lower = testo.lower()

            # Se il chunk menziona il servizio
            if any(pk in testo_lower for pk in parole_chiave):
                # Cerchiamo se ci sono prezzi citati nelle vicinanze o nel chunk
                for m in prezzo_re.finditer(testo):
                    raw_p = m.group(1) or m.group(2)
                    if not raw_p:
                        continue
                    try:
                        prezzo_trovato = float(raw_p.replace(",", "."))
                    except ValueError:
                        continue

                    # Se c'è una differenza significativa di prezzo (> 0.50€)
                    if abs(prezzo_trovato - prezzo_ufficiale_val) >= 0.50:
                        nome_doc = chunk.get("document_name") or meta.get("fonte") or "Documento"
                        conflitti.append({
                            "servizio": nome_servizio,
                            "prezzo_ufficiale": prezzo_ufficiale_val,
                            "prezzo_conflitto": prezzo_trovato,
                            "fonte_conflitto": nome_doc,
                            "tipo_fonte": tipo_fonte,
                            "priorita_risoluzione": "I Dati struttura hanno priorità 1 e prevalgono sull'altro dato.",
                            "messaggio": (
                                f"La fonte '{nome_doc}' ({tipo_fonte}) indica un prezzo di {prezzo_trovato:.2f}€ "
                                f"per '{nome_servizio}', mentre nei Dati struttura è impostato a {prezzo_ufficiale_val:.2f}€."
                            ),
                        })
                        break  # 1 conflitto per chunk basta per non duplicare

    return conflitti
