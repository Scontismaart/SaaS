import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from src.core.auth.dependencies import require_ruolo
from src.models.schemas import DisponibilitaSlot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bookings", tags=["bookings"])


def _get_booking_service(request: Request):
    svc = getattr(request.app.state, "booking_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Booking service not available")
    return svc


@router.get("/semaforo", response_model=list[DisponibilitaSlot])
async def semaforo(request: Request, data: str | None = None,
                   user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    service = _get_booking_service(request)
    org_id = user["organization_id"]
    if data:
        return await service.semaforo_giorno(org_id, data)
    return await service.prossimi_giorni_semaforo(org_id)


@router.get("/settings")
async def get_settings(request: Request,
                       user: dict = Depends(require_ruolo("owner", "manager"))):
    service = _get_booking_service(request)
    return await service.repo.get_booking_settings(user["organization_id"])


@router.put("/settings")
async def update_settings(body: dict, request: Request,
                          user: dict = Depends(require_ruolo("owner", "manager"))):
    service = _get_booking_service(request)
    return await service.aggiorna_impostazioni(
        user["organization_id"],
        capienze_orarie=body.get("capienze_orarie"),
        config=body.get("config"),
    )


@router.get("")
async def list_bookings(request: Request, data: str | None = None,
                        user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    service = _get_booking_service(request)
    return await service.repo.list_bookings(user["organization_id"], data)


@router.post("")
async def create_booking(body: dict, request: Request,
                         user: dict = Depends(require_ruolo("owner", "manager"))):
    service = _get_booking_service(request)
    try:
        return await service.create_booking(
            org_id=user["organization_id"],
            nome_cliente=body["nome_cliente"],
            telefono=body.get("telefono", ""),
            data=body["data"],
            ora=body["ora"],
            coperti=body["coperti"],
            note=body.get("note", ""),
            tipo_evento=body.get("tipo_evento", ""),
            origine=body.get("origine", "Dashboard"),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{booking_id}")
async def get_booking(booking_id: str, request: Request,
                      user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    service = _get_booking_service(request)
    b = await service.repo.get_booking(user["organization_id"], booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    return b


@router.post("/{booking_id}/confirm")
async def confirm_booking(booking_id: str, request: Request,
                          user: dict = Depends(require_ruolo("owner", "manager"))):
    service = _get_booking_service(request)
    try:
        return await service.confirm(user["organization_id"], booking_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{booking_id}/reject")
async def reject_booking(booking_id: str, body: dict = {}, request: Request = None,
                         user: dict = Depends(require_ruolo("owner", "manager"))):
    service = _get_booking_service(request)
    try:
        return await service.reject(user["organization_id"], booking_id, body.get("motivo", ""))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{booking_id}/cancel")
async def cancel_booking(booking_id: str, request: Request,
                         user: dict = Depends(require_ruolo("owner", "manager"))):
    service = _get_booking_service(request)
    b = await service.cancel(user["organization_id"], booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    return b


@router.post("/{booking_id}/mark-no-show")
async def mark_no_show(booking_id: str, request: Request,
                       user: dict = Depends(require_ruolo("owner", "manager"))):
    service = _get_booking_service(request)
    b = await service.mark_no_show(user["organization_id"], booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    return b


@router.post("/{booking_id}/mark-completed")
async def mark_completed(booking_id: str, request: Request,
                         user: dict = Depends(require_ruolo("owner", "manager"))):
    service = _get_booking_service(request)
    b = await service.mark_completed(user["organization_id"], booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    return b
