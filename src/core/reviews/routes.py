import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.routes.common import check_feature_blocked_by_plan
from src.core.auth.dependencies import require_ruolo
from src.core.db.repository import CoreRepository
from src.core.reviews.schemas import (
    ReviewApproveResponse,
    ReviewItem,
    ReviewListResponse,
)

router = APIRouter(prefix="/api/recensioni", tags=["recensioni"])
logger = logging.getLogger(__name__)


def _get_repo(request: Request) -> CoreRepository:
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(500, "Repository non inizializzato")
    return repo


def _to_item(r: dict) -> ReviewItem:
    return ReviewItem(
        id=str(r["id"]),
        organization_id=str(r["organization_id"]),
        testo=r["testo"],
        valutazione_stelle=r.get("valutazione_stelle"),
        fonte=r.get("fonte", ""),
        autore=r.get("autore", ""),
        external_id=r.get("external_id"),
        bozza_risposta=r.get("bozza_risposta", ""),
        sentiment=r.get("sentiment", ""),
        categoria=r.get("categoria", ""),
        richiede_revisione_urgente=bool(r.get("richiede_revisione_urgente", False)),
        stato=r.get("stato", "nuova"),
        published_at=r.get("published_at").isoformat() if r.get("published_at") else None,
        is_anonymized=bool(r.get("is_anonymized", False)),
        created_at=r["created_at"].isoformat(),
    )


@router.get("", response_model=ReviewListResponse)
async def list_reviews(
    request: Request,
    stato: str | None = None,
    fonte: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    repo = _get_repo(request)
    org_id = user["organization_id"]
    blocco = await check_feature_blocked_by_plan(repo, org_id, "recensioni")
    if blocco:
        raise HTTPException(status_code=403, detail=blocco)
    try:
        rows = await repo.list_reviews(org_id, stato=stato, fonte=fonte, page=page, limit=limit)
        total = await repo.count_reviews(org_id, stato=stato, fonte=fonte)
    except Exception as exc:
        logger.error("Review listing failed org_id=%s", org_id, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Impossibile recuperare le recensioni."
        ) from exc
    return ReviewListResponse(
        recensioni=[_to_item(r) for r in rows],
        total=total,
    )


@router.get("/analytics")
async def review_analytics(
    request: Request,
    giorni: int = 90,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    repo = _get_repo(request)
    org_id = user["organization_id"]
    blocco = await check_feature_blocked_by_plan(repo, org_id, "recensioni")
    if blocco:
        raise HTTPException(status_code=403, detail=blocco)
    return await repo.get_review_analytics(user["organization_id"], giorni=giorni)


@router.get("/{review_id}", response_model=ReviewItem)
async def get_review(
    review_id: str,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    repo = _get_repo(request)
    org_id = user["organization_id"]
    blocco = await check_feature_blocked_by_plan(repo, org_id, "recensioni")
    if blocco:
        raise HTTPException(status_code=403, detail=blocco)
    review = await repo.get_review(user["organization_id"], review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Recensione non trovata")
    return _to_item(review)


@router.post("/{review_id}/approva", response_model=ReviewApproveResponse)
async def approve_review(
    review_id: str,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Approvazione one-click della bozza risposta. Multi-tenant: una
    recensione di un'altra org restituisce 404 (nessuna leak informativa)."""
    repo = _get_repo(request)
    org_id = user["organization_id"]
    blocco = await check_feature_blocked_by_plan(repo, org_id, "recensioni")
    if blocco:
        raise HTTPException(status_code=403, detail=blocco)
    review = await repo.approve_review(user["organization_id"], review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Recensione non trovata")
    return ReviewApproveResponse(id=str(review["id"]), stato=review["stato"])
