"""Registrazione self-service (POST /api/auth/register).

Crea l'utente su Supabase Auth, poi organizzazione + membership owner con
trial attivo (subscription_status='trialing', trial_end = now + TRIAL_DAYS).
La sospensione a trial scaduto e' gestita da core.billing.suspension.

Sicurezza:
- rate limit per IP distribuito (Redis via RATE_LIMIT_BACKEND=redis):
  anti-abuso creazione account massiva, valido multi-worker/restart
- nessuna enumerazione account: errore generico su email gia' registrata +
  timing uniformato (il 409 non e' distinguibile per latenza dal flusso ok)
- password minima 10 caratteri di cui almeno uno speciale, validazione
  server-side (la policy Supabase va allineata a 10 nel dashboard)
"""

import asyncio
import os
import random
import re
import time

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from src.core.auth import bff, throttle
from src.core.auth.csrf import issue_csrf_token
from src.core.auth.dependencies import get_repo

router = APIRouter(prefix="/api/auth", tags=["auth"])

TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "7"))
PASSWORD_MIN = 10

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Almeno un carattere non alfanumerico (simbolo o punteggiatura)
_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")

# Anti-abuso: max 5 signup per IP all'ora (contatore distribuito)
_SIGNUP_MAX = 5
_SIGNUP_WINDOW = 60 * 60


def _signup_throttle_key(ip: str) -> str:
    return f"auth:signup:{ip}"


async def _check_signup_throttle(ip: str) -> None:
    if await throttle.is_throttled(
        _signup_throttle_key(ip), _SIGNUP_MAX, _SIGNUP_WINDOW
    ):
        raise HTTPException(
            429,
            "Troppe registrazioni da questo indirizzo. Riprova più tardi.",
        )


async def _mask_timing(started: float) -> None:
    """Uniforma la latenza del ramo 'email già registrata': senza questo,
    il 409 veloce vs la creazione-org lenta permetterebbe l'enumerazione
    delle email per tempo di risposta."""
    elapsed = time.perf_counter() - started
    target = random.uniform(0.35, 0.65)
    if elapsed < target:
        await asyncio.sleep(target - elapsed)


class RegisterBody(BaseModel):
    email: str
    password: str
    nome_attivita: str


def _client_ip(request: Request) -> str:
    from src.core.auth.trusted_network import get_client_ip
    return str(get_client_ip(request) or "unknown")


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
    if resp.status_code == 429:
        raise HTTPException(
            429,
            "Limite invio email raggiunto da Supabase. Riprova tra qualche minuto.",
        )
    if resp.status_code >= 400:
        err_msg = ""
        try:
            err_data = resp.json()
            err_msg = err_data.get("msg") or err_data.get("message") or ""
        except Exception:
            pass
        if "invalid" in err_msg.lower() and "email" in err_msg.lower():
            raise HTTPException(422, "Indirizzo email non valido o dominio non accettato.")
        raise HTTPException(502, f"Registrazione non riuscita: {err_msg}" if err_msg else "Registrazione temporaneamente non disponibile")
    return resp.json()


@router.post("/register")
async def register(body: RegisterBody, request: Request, response: Response):
    ip = _client_ip(request)
    await _check_signup_throttle(ip)
    # Ogni tentativo consuma uno slot del limite (stessa semantica del
    # vecchio contatore in-memory: 5/ora/IP, il sesto è bloccato).
    await throttle.record_event(_signup_throttle_key(ip), _SIGNUP_WINDOW)

    email = body.email.strip().lower()
    nome_attivita = body.nome_attivita.strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Email non valida")
    if len(body.password) < PASSWORD_MIN or not _SPECIAL_RE.search(body.password):
        raise HTTPException(
            422,
            f"La password deve avere almeno {PASSWORD_MIN} caratteri "
            "e includere almeno un carattere speciale (es. ! @ # $ %)",
        )
    if not nome_attivita or len(nome_attivita) > 120:
        raise HTTPException(422, "Inserisci il nome della tua attività")

    started = time.perf_counter()
    try:
        data = await supabase_signup(email, body.password)
    except HTTPException as exc:
        if exc.status_code == 409:
            await _mask_timing(started)
        raise

    user = data.get("user") if isinstance(data.get("user"), dict) else data
    auth_user_id = user.get("id") or data.get("id")
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
