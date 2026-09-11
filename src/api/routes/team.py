"""Team & Multi-User Management API Routes (Invarianti 1, 2, 8).

Gestisce:
- Elenco membri del team dell'organizzazione (/api/team/members)
- Aggiunta/invito collaboratori con enforcement rigido di users_limit per piano
- Rimozione collaboratori e gestione ruoli (manager, staff)
"""

import logging
import uuid
import re
from typing import Literal
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.dependencies import get_pool, require_ruolo
from src.api.routes.common import audit_event
from src.core.billing.plans import PLANS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/team", tags=["team"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AddTeamMemberInput(BaseModel):
    email: str
    ruolo: Literal["manager", "staff"] = "staff"

    @field_validator("email")
    @classmethod
    def validate_email_fmt(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Indirizzo email non valido")
        return v


class UpdateRoleInput(BaseModel):
    ruolo: Literal["manager", "staff"]


class TeamMemberItem(BaseModel):
    id: str
    user_id: str
    nome: str
    email: str
    ruolo: str
    joined_at: str | None = None


class TeamListResponse(BaseModel):
    members: list[TeamMemberItem]
    total: int
    users_limit: int | None
    can_add_more: bool


@router.get("/members", response_model=TeamListResponse)
async def list_team_members(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Restituisce l'elenco dei membri dell'organizzazione, il limite del piano e la disponibilità."""
    org_id = user["organization_id"]
    pool = get_pool(request)

    async with pool.acquire() as conn:
        org_row = await conn.fetchrow(
            "SELECT plan, users_limit, subscription_status FROM organizations WHERE id = $1::uuid",
            uuid.UUID(org_id),
        )
        plan = org_row["plan"] if org_row else None
        # Se non c'è un piano o l'organizzazione è in prova gratuita, applichiamo il tier 'pro' (3 utenti)
        effective_plan = plan or "pro"
        plan_def = PLANS.get(effective_plan)
        if org_row and org_row["users_limit"] is not None:
            users_limit = org_row["users_limit"]
        elif plan_def:
            users_limit = plan_def.users_limit
        else:
            users_limit = 3

        rows = await conn.fetch("""
            SELECT om.id, om.user_id, up.nome, up.email, om.ruolo, om.joined_at
            FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE om.organization_id = $1::uuid
            ORDER BY
              CASE om.ruolo WHEN 'owner' THEN 0 WHEN 'manager' THEN 1 ELSE 2 END,
              om.joined_at ASC
        """, uuid.UUID(org_id))

    members = [
        TeamMemberItem(
            id=str(r["id"]),
            user_id=str(r["user_id"]),
            nome=r["nome"] or r["email"].split("@")[0],
            email=r["email"],
            ruolo=r["ruolo"],
            joined_at=r["joined_at"].isoformat() if r["joined_at"] else None,
        )
        for r in rows
    ]
    total = len(members)
    can_add_more = (users_limit is None) or (total < users_limit)

    return TeamListResponse(
        members=members,
        total=total,
        users_limit=users_limit,
        can_add_more=can_add_more,
    )


@router.post("/members", response_model=TeamMemberItem)
async def add_team_member(
    body: AddTeamMemberInput,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Aggiunge un collaboratore all'organizzazione verificando il limite del piano."""
    org_id = user["organization_id"]
    pool = get_pool(request)

    # I manager possono invitare solo staff
    if user["ruolo"] == "manager" and body.ruolo != "staff":
        raise HTTPException(
            status_code=403,
            detail="I manager possono aggiungere solo collaboratori con ruolo 'staff'.",
        )

    async with pool.acquire() as conn, conn.transaction():
        # 1. Verifica limiti piano
        org_row = await conn.fetchrow(
            "SELECT plan, users_limit, subscription_status FROM organizations WHERE id = $1::uuid FOR UPDATE",
            uuid.UUID(org_id),
        )
        if not org_row:
            raise HTTPException(404, "Organizzazione non trovata")

        plan = org_row["plan"]
        effective_plan = plan or "pro"
        plan_def = PLANS.get(effective_plan)
        if org_row["users_limit"] is not None:
            users_limit = org_row["users_limit"]
        elif plan_def:
            users_limit = plan_def.users_limit
        else:
            users_limit = 3

        # Se il piano ha un limite numerico impostato, verifichiamo la capienza
        if users_limit is not None:
            current_count = await conn.fetchval(
                "SELECT count(*) FROM organization_memberships WHERE organization_id = $1::uuid",
                uuid.UUID(org_id),
            )
            if current_count >= users_limit:
                piano_nome = "Essenziale" if effective_plan == "starter" else ("Crescita (in prova)" if not plan else "Crescita")
                upgrade_suggerito = "Crescita (fino a 3 utenti)" if effective_plan == "starter" else "Scala (utenti illimitati)"
                raise HTTPException(
                    status_code=403,
                    detail=f"Limite utenti raggiunto per il piano {piano_nome} (massimo {users_limit} utente/i). "
                           f"Effettua l'upgrade al piano {upgrade_suggerito} per aggiungere altri collaboratori.",
                )

        # 2. Ricerca utente in user_profiles
        target_user = await conn.fetchrow(
            "SELECT id, nome, email FROM user_profiles WHERE LOWER(email) = LOWER($1)",
            body.email.strip(),
        )
        if not target_user:
            raise HTTPException(
                status_code=404,
                detail=f"Nessun utente registrato trovato con l'email '{body.email}'. "
                       "Il collaboratore deve prima completare la registrazione su Melpis.",
            )

        target_user_id = target_user["id"]

        # 3. Verifica se già membro
        existing_membership = await conn.fetchrow(
            "SELECT ruolo FROM organization_memberships WHERE organization_id = $1::uuid AND user_id = $2::uuid",
            uuid.UUID(org_id), target_user_id,
        )
        if existing_membership:
            raise HTTPException(
                status_code=409,
                detail=f"L'utente '{body.email}' fa già parte di questa organizzazione con ruolo '{existing_membership['ruolo']}'.",
            )

        # 4. Inserimento membership
        new_membership = await conn.fetchrow("""
            INSERT INTO organization_memberships (organization_id, user_id, ruolo, joined_at)
            VALUES ($1::uuid, $2::uuid, $3, NOW())
            RETURNING id, organization_id, user_id, ruolo, joined_at
        """, uuid.UUID(org_id), target_user_id, body.ruolo)

    await audit_event(
        request,
        user,
        "team.membro_aggiunto",
        target_table="organization_memberships",
        target_id=str(new_membership["id"]),
        details={
            "user_id": str(target_user_id),
            "email": target_user["email"],
            "ruolo": body.ruolo,
        },
    )

    return TeamMemberItem(
        id=str(new_membership["id"]),
        user_id=str(target_user_id),
        nome=target_user["nome"] or target_user["email"].split("@")[0],
        email=target_user["email"],
        ruolo=new_membership["ruolo"],
        joined_at=new_membership["joined_at"].isoformat(),
    )


@router.delete("/members/{member_user_id}")
async def remove_team_member(
    member_user_id: str,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Rimuove un collaboratore dall'organizzazione."""
    org_id = user["organization_id"]
    pool = get_pool(request)

    try:
        t_uid = uuid.UUID(member_user_id)
    except ValueError:
        raise HTTPException(400, "ID utente non valido")

    if str(t_uid) == str(user.get("user_id")):
        raise HTTPException(400, "Non puoi rimuovere te stesso dal team.")

    async with pool.acquire() as conn:
        target = await conn.fetchrow("""
            SELECT om.id, om.ruolo, up.email
            FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE om.organization_id = $1::uuid AND om.user_id = $2::uuid
        """, uuid.UUID(org_id), t_uid)

        if not target:
            raise HTTPException(404, "Collaboratore non trovato nell'organizzazione.")

        if target["ruolo"] == "owner":
            raise HTTPException(400, "Non è possibile rimuovere il proprietario dell'organizzazione.")

        if user["ruolo"] == "manager" and target["ruolo"] == "manager":
            raise HTTPException(403, "I manager possono rimuovere solo membri dello staff.")

        await conn.execute(
            "DELETE FROM organization_memberships WHERE organization_id = $1::uuid AND user_id = $2::uuid",
            uuid.UUID(org_id), t_uid,
        )

    await audit_event(
        request,
        user,
        "team.membro_rimosso",
        target_table="organization_memberships",
        target_id=str(target["id"]),
        details={"user_id": member_user_id, "email": target["email"], "ruolo": target["ruolo"]},
    )

    return {"detail": f"Collaboratore {target['email']} rimosso con successo."}


@router.patch("/members/{member_user_id}")
async def update_team_member_role(
    member_user_id: str,
    body: UpdateRoleInput,
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
):
    """Modifica il ruolo di un collaboratore (solo proprietario)."""
    org_id = user["organization_id"]
    pool = get_pool(request)

    try:
        t_uid = uuid.UUID(member_user_id)
    except ValueError:
        raise HTTPException(400, "ID utente non valido")

    async with pool.acquire() as conn:
        target = await conn.fetchrow(
            "SELECT id, ruolo FROM organization_memberships WHERE organization_id = $1::uuid AND user_id = $2::uuid",
            uuid.UUID(org_id), t_uid,
        )
        if not target:
            raise HTTPException(404, "Collaboratore non trovato.")

        if target["ruolo"] == "owner":
            raise HTTPException(400, "Non è possibile modificare il ruolo del proprietario.")

        await conn.execute(
            "UPDATE organization_memberships SET ruolo = $3 WHERE organization_id = $1::uuid AND user_id = $2::uuid",
            uuid.UUID(org_id), t_uid, body.ruolo,
        )

    await audit_event(
        request,
        user,
        "team.ruolo_aggiornato",
        target_table="organization_memberships",
        target_id=str(target["id"]),
        details={"user_id": member_user_id, "vecchio_ruolo": target["ruolo"], "nuovo_ruolo": body.ruolo},
    )

    return {"detail": f"Ruolo aggiornato a '{body.ruolo}'."}
