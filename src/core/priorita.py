from src.models.schemas import RispostaOutput, Priorita, RispostaRecensioneOutput

CATEGORIE_URGENTI = {
    "reclamo",
    "allergia",
    "urgenza",
    "emergenza",
}


def calcola_priorita(risposta: RispostaOutput) -> Priorita:
    if not risposta.richiede_umano:
        return Priorita.BASSA

    if risposta.categoria.strip().lower() in CATEGORIE_URGENTI:
        return Priorita.ALTA

    return Priorita.MEDIA


def calcola_priorita_recensione(
    stelle: int | None,
    output: RispostaRecensioneOutput,
) -> Priorita:
    if stelle is not None and stelle <= 2:
        return Priorita.ALTA

    if output.richiede_revisione_urgente:
        return Priorita.ALTA

    if output.sentiment == "negativa":
        return Priorita.MEDIA

    if stelle is not None and stelle == 3 and output.sentiment != "positiva":
        return Priorita.MEDIA

    return Priorita.BASSA
