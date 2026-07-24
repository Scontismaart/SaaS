from src.core.review_sources.base import FonteRecensioni
from src.models.schemas import RecensioneInput


class FonteManuale(FonteRecensioni):
    def recupera_nuove_recensioni(self) -> list[RecensioneInput]:
        return []
