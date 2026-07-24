from src.core.review_sources.base import FonteRecensioni
from src.models.schemas import RecensioneInput


class FonteGoogle(FonteRecensioni):
    def recupera_nuove_recensioni(self) -> list[RecensioneInput]:
        raise NotImplementedError(
            "Google Business Profile API — da implementare. "
            "Usa l'API ufficiale, non scraping."
        )
