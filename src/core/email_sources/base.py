from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AllegatoInput:
    nome: str
    bytes: bytes


@dataclass
class EmailInput:
    mittente: str
    oggetto: str
    corpo_testo: str
    allegati: list[AllegatoInput] = field(default_factory=list)
    ricevuta_il: datetime = field(default_factory=datetime.now)
