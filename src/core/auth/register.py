"""Registrazione self-service (POST /api/auth/register).

Crea l'utente su Supabase Auth, poi organizzazione + membership owner con
trial attivo (subscription_status='trialing', trial_end = now + TRIAL_DAYS).
La sospensione a trial scaduto e' gestita da core.billing.suspension.

Sicurezza:
- rate limit per IP (anti-abuso creazione account massiva)
- nessuna enumerazione account: errore generico su email gia' registrata
- password minima 8 caratteri, validazione server-side
"""

import os
import re
import time

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from src.core.auth import bff
from src.core.auth.csrf import issue_csrf_token
from src.core.auth.dependencies import get_repo

router = APIRouter(prefix="/api/auth", tags=["auth"])

TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "14"))
PASSWORD_MIN = 8

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Anti-abuso: max 5 signup per IP all'ora (in-memory, come il throttle login)
_SIGNUPS: dict[str, list[float]] = {}
_SIGNUP_MAX = 5
_SIGNUP_WINDOW = 60 * 60


class RegisterBody(BaseModel):
    email: str
    password: str
    nome_attivita: str


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_signup_throttle(ip: str) -> None:
    now = time.time()
    cutoff = now - _SIGNUP_WINDOW
    recent = [t for t in _SIGNUPS.get(ip, []) if t > cutoff]
    recent.append(now)
    if len(recent) > _SIGNUP_MAX:
        _SIGNUPS[ip] = recent
        raise HTTPException(
            status_code=429,
            detail="Troppe registrazioni da questo indirizzo. Riprova più tardi.",
        )
    _SIGNUPS[ip] = recent


async def supabase_signup(email: str, password: str) -> dict:
    """POST /auth/v1/signup verso Supabase Auth (chiave anon)."""
    url = bff._supabase_url()
    client = await bff._client()
    try:
        resp = await client.post(
            f"{url}/auth/v1/signup",
            json={"email": email, "password": password},
            headers={"apikey": bff._anon_key(), "Content-Type": "application/json"},
        )
    except httpx.HTTPError:
        raise HTTPException(502, "Servizio di registrazione non raggiungibile")
    if resp.status_code == 422:
        # Email già registrata o password debole: messaggio generico che non
        # conferma l'esistenza dell'account (anti-enumeration).
        raise HTTPException(
            409,
            "Registrazione non riuscita: controlla i dati "
            "o accedi se hai già un account.",
        )
    if resp.status_code >= 400:
        raise HTTPException(502, "Registrazione temporaneamente non disponibile")
    return resp.json()


@router.post("/register")
async def register(body: RegisterBody, request: Request, response: Response):
    ip = _client_ip(request)
    _check_signup_throttle(ip)

    email = body.email.strip().lower()
    nome_attivita = body.nome_attivita.strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Email non valida")
    if len(body.password) < PASSWORD_MIN:
        raise HTTPException(
            422, f"La password deve avere almeno {PASSWORD_MIN} caratteri"
        )
    if not nome_attivita or len(nome_attivita) > 120:
        raise HTTPException(422, "Inserisci il nome della tua attività")

    data = await supabase_signup(email, body.password)

    user = data.get("user") or {}
    auth_user_id = user.get("id")
    if not auth_user_id:
        raise HTTPException(502, "Registrazione incompleta, riprova")

    repo = get_repo(request)
    try:
        org = await repo.create_organization_with_owner(
            auth_user_id, nome_attivita, TRIAL_DAYS
        )
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))

    # Se Supabase restituisce una sessione (email auto-confirm attiva),
    # autentichiamo subito; altrimenti il client chiede la verifica email.
    session = data.get("access_token") and data
    csrf_token = None
    if session:
        from src.core.auth.routes import _set_session_cookies
        _set_session_cookies(response, data)
        csrf_token = issue_csrf_token(response)

    return {
        "ok": True,
        "organization_id": org["organization_id"],
        "email_verified": bool(data.get("access_token")),
        "csrf_token": csrf_token,
    }
