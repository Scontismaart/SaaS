from src.core.review_sources.base import FonteRecensioni
from src.models.schemas import RecensioneInput


class FonteTripAdvisor(FonteRecensioni):
    def recupera_nuove_recensioni(self) -> list[RecensioneInput]:
        # Ingresso manuale via mini-form (l'operatore incolla la recensione
        # ricevuta su TripAdvisor). Nessun fetch automatico: le API ufficiali
        # TripAdvisor richiedono un accordo commerciale e lo scraping viola
        # i Terms of Service, quindi qui non recuperiamo nulla da soli.
        return []
