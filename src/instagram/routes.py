from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.core.auth.dependencies import require_ruolo
from src.instagram.repository import InstagramRepository

router = APIRouter(prefix="/api/instagram", tags=["instagram"])


def _get_igrepo(request: Request) -> InstagramRepository:
    pool = request.app.state.pool
    if pool is None:
        raise HTTPException(500, "Database not available")
    return InstagramRepository(pool=pool)


class InstagramAccountRequest(BaseModel):
    ig_user_id: str = Field(min_length=1, description="IG professional account id (recipient.id nei webhook)")
    access_token: str = Field(min_length=1)


class InstagramAccountResponse(BaseModel):
    ig_user_id: str
    created_at: str
    updated_at: str


@router.post("/account", response_model=InstagramAccountResponse)
async def save_account(
    body: InstagramAccountRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Collega l'account Instagram del locale all'organizzazione. Il token
    page e' cifrato Fernet a riposo (stesso pattern whatsapp_accounts)."""
    org_id = user["organization_id"]
    igrepo = _get_igrepo(request)
    try:
        row = await igrepo.save_instagram_account(org_id, body.ig_user_id.strip(), body.access_token.strip())
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return InstagramAccountResponse(
        ig_user_id=row["ig_user_id"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


@router.get("/account", response_model=InstagramAccountResponse)
async def get_account(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user["organization_id"]
    igrepo = _get_igrepo(request)
    row = await igrepo.get_instagram_account(org_id)
    if not row:
        raise HTTPException(status_code=404, detail="Nessun account Instagram collegato")
    return InstagramAccountResponse(
        ig_user_id=row["ig_user_id"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


@router.delete("/account")
async def delete_account(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    org_id = user["organization_id"]
    igrepo = _get_igrepo(request)
    deleted = await igrepo.delete_instagram_account(org_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Nessun account Instagram collegato")
    return {"deleted": True}
