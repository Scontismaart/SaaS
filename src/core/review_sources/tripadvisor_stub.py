from src.core.review_sources.base import FonteRecensioni
from src.models.schemas import RecensioneInput


class FonteTripAdvisor(FonteRecensioni):
    def recupera_nuove_recensioni(self) -> list[RecensioneInput]:
        raise NotImplementedError(
            "TripAdvisor API — da implementare. "
            "Valutare Terms of Service prima di procedere."
        )
