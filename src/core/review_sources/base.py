from abc import ABC, abstractmethod
from src.models.schemas import RecensioneInput


class FonteRecensioni(ABC):
    @abstractmethod
    def recupera_nuove_recensioni(self) -> list[RecensioneInput]:
        ...
