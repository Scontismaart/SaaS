from pydantic import BaseModel
from typing import Optional


class ReviewItem(BaseModel):
    id: str
    organization_id: str
    testo: str
    valutazione_stelle: Optional[int] = None
    fonte: str
    autore: str
    external_id: Optional[str] = None
    bozza_risposta: str
    sentiment: str
    categoria: str
    richiede_revisione_urgente: bool
    stato: str
    published_at: Optional[str] = None
    is_anonymized: bool
    created_at: str


class ReviewListResponse(BaseModel):
    recensioni: list[ReviewItem]
    total: int


class ReviewApproveResponse(BaseModel):
    id: str
    stato: str
