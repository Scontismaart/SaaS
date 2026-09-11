"""Endpoint BFF di autenticazione (/api/auth/*).

Il frontend si autentica qui: il backend scambia le credenziali con Supabase
Auth e restituisce la sessione in cookie HttpOnly+Secure+SameSite=Strict.
Nessun token transita dal client (niente localStorage, niente header Bearer).
"""

import hashlib
import os
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.core.auth import bff, throttle
from src.core.auth.audit import audit_log
from src.core.auth.csrf import clear_csrf_token, issue_csrf_token
from src.core.auth.denylist import is_token_revoked, revoke_token
from src.core.auth.dependencies import get_organization_context, get_repo, require_ruolo

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Durata trial alla creazione org (registrazione normale e primo accesso
# Google usano la stessa variabile d'ambiente).
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "7"))

# Anti brute-force su /api/auth/login: fallimenti consecutivi per IP.
# Contatori distribuiti (Redis quando RATE_LIMIT_BACKEND=redis): validi con
# più worker/repliche e sopravvivono ai restart. Finestra scorrevole.
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_LOCKOUT_SECONDS = _LOGIN_WINDOW_SECONDS  # la finestra stessa è il lockout

# ── Google OAuth (PKCE server-side) ────────────────────────────────────
# Il verifier viaggia SOLO in cookie HttpOnly: il browser non vede mai il
# verifier (i token restano fuori da JS, come per il login BFF). Lo `state`
# OAuth è gestito internamente da Supabase Auth: passarne uno custom rompe
# il flusso (bad_oauth_state); il binding anti-CSRF è garantito da PKCE,
# perché lo scambio del codice richiede il verifier del nostro cookie.
# SameSite=Lax è richiesto: il callback arriva da un redirect top-level di
# Google, che i cookie Strict non includerebbero.
_OAUTH_VERIFIER_COOKIE = "wa_oauth_verifier"
_OAUTH_NEXT_COOKIE = "wa_oauth_next"
_OAUTH_STATE_MAX_AGE = 600  # 10 minuti per completare il round-trip


def _oauth_cookie_name(base: str) -> str:
    return f"__Host-{base}" if bff.cookie_secure() else base


def _safe_next(next_path: str | None) -> str:
    """Accetta solo path relativi interni (niente //host, backslash, scheme)."""
    if not next_path:
        return "/app/"
    # I valori cookie con caratteri speciali tornano quotati dal browser.
    path = next_path.strip('"')
    if (
        path.startswith("/")
        and not path.startswith("//")
        and "\\" not in path
        and "://" not in path
    ):
        return path
    return "/app/"


class LoginRequest(BaseModel):
    email: str
    password: str


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _login_throttle_key(ip: str) -> str:
    return f"auth:login-fail:{ip}"


async def _check_login_throttle(ip: str) -> None:
    if await throttle.is_throttled(
        _login_throttle_key(ip), _LOGIN_MAX_FAILURES, _LOGIN_WINDOW_SECONDS
    ):
        raise HTTPException(
            status_code=429,
            detail="Troppi tentativi di accesso. Riprova tra 15 minuti.",
        )


async def _record_login_failure(ip: str) -> None:
    await throttle.record_event(_login_throttle_key(ip), _LOGIN_LOCKOUT_SECONDS)


async def _record_login_success(ip: str) -> None:
    await throttle.clear_events(_login_throttle_key(ip))


def _set_session_cookies(response: Response, data: dict) -> None:
    common = {
        "httponly": True,
        "secure": bff.cookie_secure(),
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(bff.access_cookie_name(), data["access_token"], **common)
    response.set_cookie(bff.refresh_cookie_name(), data["refresh_token"], **common)


def _clear_session_cookies(response: Response) -> None:
    for name in (bff.access_cookie_name(), bff.refresh_cookie_name()):
        response.delete_cookie(name, path="/")
    clear_csrf_token(response)


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    ip = _client_ip(request)
    await _check_login_throttle(ip)
    try:
        data = await bff.login(body.email.strip(), body.password)
    except HTTPException:
        await _record_login_failure(ip)
        raise
    await _record_login_success(ip)
    _set_session_cookies(response, data)
    csrf_token = issue_csrf_token(response)
    return {"ok": True, "email": body.email.strip(), "csrf_token": csrf_token}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    rt = request.cookies.get(bff.refresh_cookie_name())
    if not rt or await is_token_revoked(rt):
        raise HTTPException(status_code=401, detail="Sessione scaduta")
    # user_key anonimo: digest del token, mai il token grezzo in memoria
    user_key = hashlib.sha256(rt.encode()).hexdigest()
    data = await bff.refresh(rt, user_key)
    await revoke_token(rt)
    _set_session_cookies(response, data)
    csrf_token = issue_csrf_token(response)
    return {"ok": True, "csrf_token": csrf_token}


def _nome_attivita_da_utente(user: dict) -> str:
    """Nome organizzazione per il provisioning JIT: full name Google,
    altrimenti prefisso email. Trim + limite 120 come la validazione
    della registrazione normale."""
    meta = user.get("user_metadata") if isinstance(user, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    email = user.get("email") or ""
    nome = (
        (meta.get("full_name") or "").strip()
        or (meta.get("name") or "").strip()
        or email.split("@")[0].strip()
        or "La mia attività"
    )
    return nome[:120] or "La mia attività"


@router.get("/google/start")
async def google_start(next: str | None = None):
    """Avvio login Google: genera il PKCE verifier, lo mette in cookie
    HttpOnly di breve durata e reindirizza al authorize endpoint Supabase.
    Lo `state` OAuth non va passato: lo genera Supabase internamente."""
    next_path = _safe_next(next)
    code_verifier = secrets.token_urlsafe(48)
    redirect_to = f"{bff.public_app_url()}/api/auth/google/callback"
    authorize_url = bff.google_authorize_url(
        redirect_to, bff.pkce_challenge(code_verifier)
    )

    # I cookie vanno messi sulla redirect stessa: FastAPI non unisce gli
    # header del parametro `response` quando si torna una Response diretta.
    redirect = RedirectResponse(authorize_url, status_code=302)
    common = {
        "httponly": True,
        "secure": bff.cookie_secure(),
        "samesite": "lax",
        "path": "/",
        "max_age": _OAUTH_STATE_MAX_AGE,
    }
    redirect.set_cookie(_oauth_cookie_name(_OAUTH_VERIFIER_COOKIE), code_verifier, **common)
    # Il path di destinazione post-login viaggia nel cookie (non nell'URL di
    # authorize: redirect_to deve restare identico agli URL consentiti Supabase).
    redirect.set_cookie(_oauth_cookie_name(_OAUTH_NEXT_COOKIE), next_path, **common)
    return redirect


@router.get("/google/callback")
async def google_callback(request: Request):
    """Callback Google→Supabase: scambia il codice PKCE con i token di
    sessione e imposta gli stessi cookie del login BFF. Lo `state` che torna
    indietro è l'uuid interno di Supabase (opaco): l'integrità del flusso è
    garantita da PKCE — senza il verifier nel cookie HttpOnly lo scambio
    fallisce. Qualsiasi anomalia → /accedi/?errore=google (fail-closed)."""
    error_redirect = RedirectResponse("/accedi/?errore=google", status_code=302)

    # Google/Supabase possono rimandare un errore OAuth (access denied ecc.)
    if request.query_params.get("error"):
        return error_redirect

    auth_code = request.query_params.get("code")
    cookie_verifier = request.cookies.get(_oauth_cookie_name(_OAUTH_VERIFIER_COOKIE))
    cookie_next = _safe_next(request.cookies.get(_oauth_cookie_name(_OAUTH_NEXT_COOKIE)))
    if not auth_code or not cookie_verifier:
        return error_redirect

    try:
        data = await bff.exchange_pkce(auth_code, cookie_verifier)

        # Primo accesso Google: Supabase ha creato l'utente (e il trigger DB
        # il profilo), ma organizzazione + membership esistono solo se l'utente
        # e' passato dalla registrazione email/password. Senza provisioning,
        # /me risponderebbe 403 e il frontend rispedirebbe al login: loop.
        # Idempotente: se ha gia' una org non fa nulla.
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        auth_user_id = user.get("id")
        if auth_user_id:
            repo = get_repo(request)
            memberships = await repo.get_memberships_by_auth(str(auth_user_id))
            if not memberships:
                await repo.get_or_create_organization_with_owner(
                    str(auth_user_id),
                    _nome_attivita_da_utente(user),
                    TRIAL_DAYS,
                )
    except HTTPException:
        return error_redirect
    except RuntimeError:
        return error_redirect

    target_url = cookie_next
    redirect = RedirectResponse(target_url, status_code=302)
    _set_session_cookies(redirect, data)
    issue_csrf_token(redirect)

    # I cookie temporanei OAuth vanno consumati: non riutilizzabili.
    for name in (
        _oauth_cookie_name(_OAUTH_VERIFIER_COOKIE),
        _oauth_cookie_name(_OAUTH_NEXT_COOKIE),
    ):
        redirect.delete_cookie(name, path="/")

    return redirect


@router.post("/logout")
async def logout(request: Request, response: Response):
    at = request.cookies.get(bff.access_cookie_name())
    rt = request.cookies.get(bff.refresh_cookie_name())
    if at:
        await revoke_token(at)
        await bff.logout(at)
    if rt:
        await revoke_token(rt)
    _clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return {
        "email": user.get("email"),
        "organization_id": user.get("organization_id"),
        "ruolo": user.get("ruolo"),
        "user_id": user.get("user_id"),
        "source": user.get("source"),
    }


# ── Sicurezza account: cambio password/email (proxy Supabase) ──────────
# La sessione valida nel cookie HttpOnly è la prova d'identità: Supabase
# non richiede la password corrente per il cambio. Rate limit per IP anti
# abuso; policy password identica alla registrazione (register.py).

_ACCOUNT_CHANGE_MAX = 5
_ACCOUNT_CHANGE_WINDOW = 60 * 60
_PASSWORD_MIN = 10
_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PasswordChange(BaseModel):
    password: str
    current_password: str


class EmailChange(BaseModel):
    email: str


def _account_throttle_key(ip: str) -> str:
    return f"auth:account:{ip}"


async def _check_account_throttle(ip: str) -> None:
    if await throttle.is_throttled(
        _account_throttle_key(ip), _ACCOUNT_CHANGE_MAX, _ACCOUNT_CHANGE_WINDOW
    ):
        raise HTTPException(
            429, "Troppe modifiche account. Riprova tra un'ora."
        )


def _require_access_token(request: Request) -> str:
    token = request.cookies.get(bff.access_cookie_name())
    if not token:
        raise HTTPException(401, "Sessione scaduta: effettua di nuovo il login")
    return token


async def _supabase_get_user(token: str) -> dict:
    import httpx

    client = await bff._client()
    try:
        resp = await client.get(
            f"{bff._supabase_url()}/auth/v1/user",
            headers={
                "apikey": bff._anon_key(),
                "Authorization": f"Bearer {token}",
            },
        )
    except httpx.HTTPError:
        raise HTTPException(502, "Servizio autenticazione non raggiungibile")
    if resp.status_code == 401:
        raise HTTPException(401, "Sessione scaduta: effettua di nuovo il login")
    if resp.status_code >= 400:
        raise HTTPException(502, "Impossibile recuperare i dati dell'account")
    return resp.json()


async def _supabase_update_user(token: str, payload: dict) -> dict:
    import httpx

    client = await bff._client()
    try:
        resp = await client.put(
            f"{bff._supabase_url()}/auth/v1/user",
            json=payload,
            headers={
                "apikey": bff._anon_key(),
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
    except httpx.HTTPError:
        raise HTTPException(502, "Servizio autenticazione non raggiungibile")
    if resp.status_code == 401:
        raise HTTPException(401, "Sessione scaduta: effettua di nuovo il login")
    if resp.status_code == 422:
        raise HTTPException(
            422, "Dati non validi (password troppo debole o email non accettata)"
        )
    if resp.status_code == 429:
        raise HTTPException(429, "Troppe richieste. Riprova tra qualche minuto")
    if resp.status_code >= 400:
        raise HTTPException(502, "Modifica non riuscita, riprova")
    return resp.json()


@router.post("/password")
async def change_password(body: PasswordChange, request: Request):
    ip = _client_ip(request)
    await _check_account_throttle(ip)
    await throttle.record_event(_account_throttle_key(ip), _ACCOUNT_CHANGE_WINDOW)

    pwd = body.password
    if len(pwd) < _PASSWORD_MIN or not _SPECIAL_RE.search(pwd):
        raise HTTPException(
            422,
            f"La password deve avere almeno {_PASSWORD_MIN} caratteri "
            "e includere almeno un carattere speciale (es. ! @ # $ %)",
        )
    if not body.current_password or not body.current_password.strip():
        raise HTTPException(400, "Inserisci la password attuale per confermare la modifica")

    token = _require_access_token(request)

    # Re-autenticazione: verifichiamo crittograficamente la password attuale su Supabase
    user_info = await _supabase_get_user(token)
    user_email = user_info.get("email") if isinstance(user_info, dict) else None
    if user_email:
        try:
            await bff.login(user_email, body.current_password)
        except Exception:
            raise HTTPException(403, "La password attuale non è corretta")

    res_user = await _supabase_update_user(token, {"password": pwd})
    repo = getattr(request.app.state, "repo", None)
    auth_user_id = res_user.get("id") if isinstance(res_user, dict) else None
    if repo and auth_user_id:
        try:
            memberships = await repo.get_memberships_by_auth(str(auth_user_id))
            if memberships:
                org_id = str(memberships[0]["organization_id"])
                u_id = str(memberships[0]["user_id"])
                await audit_log(
                    repo,
                    organization_id=org_id,
                    action="account.password_cambiata",
                    user_id=u_id,
                    auth_user_id=str(auth_user_id),
                    target_table="user_profiles",
                    target_id=u_id,
                    details={"email": res_user.get("email"), "ip": ip},
                )
        except Exception:
            pass
    return {"ok": True, "message": "Password aggiornata"}


@router.post("/send-password-reset")
async def send_password_reset(request: Request):
    ip = _client_ip(request)
    await _check_account_throttle(ip)
    await throttle.record_event(_account_throttle_key(ip), _ACCOUNT_CHANGE_WINDOW)

    token = _require_access_token(request)
    user = await _supabase_get_user(token)
    email = user.get("email") if isinstance(user, dict) else None
    if not email:
        raise HTTPException(400, "Email dell'account non trovata")

    import httpx
    client = await bff._client()
    try:
        resp = await client.post(
            f"{bff._supabase_url()}/auth/v1/recover",
            json={"email": email},
            headers={"apikey": bff._anon_key(), "Content-Type": "application/json"},
        )
    except httpx.HTTPError:
        raise HTTPException(502, "Servizio autenticazione non raggiungibile")
    if resp.status_code == 429:
        raise HTTPException(429, "Troppe richieste di reset. Riprova tra qualche minuto")
    if resp.status_code >= 400:
        raise HTTPException(502, "Impossibile inviare il link di reset, riprova più tardi")

    parts = email.split("@")
    if len(parts) == 2:
        uname = parts[0]
        masked_user = uname[:2] + "•••" if len(uname) > 2 else uname + "•••"
        email_masked = f"{masked_user}@{parts[1]}"
    else:
        email_masked = email

    return {
        "ok": True,
        "email_masked": email_masked,
        "message": f"Link di reset inviato a {email_masked}",
    }


@router.post("/email")
async def change_email(body: EmailChange, request: Request):
    ip = _client_ip(request)
    await _check_account_throttle(ip)
    await throttle.record_event(_account_throttle_key(ip), _ACCOUNT_CHANGE_WINDOW)

    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Email non valida")
    token = _require_access_token(request)
    user = await _supabase_update_user(token, {"email": email})
    # Con "Confirm email" attivo Supabase compila new_email e invia il link:
    # la vecchia email resta attiva fino alla conferma.
    conferma_richiesta = bool(user.get("new_email")) if isinstance(user, dict) else False
    auth_user_id = user.get("id") if isinstance(user, dict) else None
    repo = getattr(request.app.state, "repo", None)
    if repo and auth_user_id:
        try:
            memberships = await repo.get_memberships_by_auth(str(auth_user_id))
            if memberships:
                org_id = str(memberships[0]["organization_id"])
                u_id = str(memberships[0]["user_id"])
                await audit_log(
                    repo,
                    organization_id=org_id,
                    action="account.email_cambiata",
                    user_id=u_id,
                    auth_user_id=str(auth_user_id),
                    target_table="user_profiles",
                    target_id=u_id,
                    details={
                        "old_email": user.get("email"),
                        "new_email": email,
                        "conferma_richiesta": conferma_richiesta,
                        "ip": ip,
                    },
                )
        except Exception:
            pass
    return {
        "ok": True,
        "email": user.get("email") if isinstance(user, dict) else None,
        "conferma_richiesta": conferma_richiesta,
        "message": (
            "Controlla la nuova casella: ti è arrivato il link di conferma"
            if conferma_richiesta
            else "Email aggiornata"
        ),
    }


# ── Recupero password (recover + reset) ────────────────────────────────
# Recover: l'utente NON è autenticato, quindi niente sessione; Supabase
# invia l'email con il link di recovery. Risposta sempre identica a
# prescindere dall'esistenza dell'account: nessuna enumerazione.
# Reset: il link di recovery rimanda al frontend con access_token +
# type=recovery nell'hash dell'URL; il token viene usato come Bearer per
# PUT /auth/v1/user (stessa via del cambio password da autenticato).
# Rate limit condiviso con le altre modifiche account (5/ora/IP).


class RecoverRequest(BaseModel):
    email: str


class ResetPassword(BaseModel):
    access_token: str
    password: str


@router.post("/recover")
async def recover_password(body: RecoverRequest, request: Request):
    ip = _client_ip(request)
    await _check_account_throttle(ip)
    await throttle.record_event(_account_throttle_key(ip), _ACCOUNT_CHANGE_WINDOW)

    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Email non valida")

    import httpx

    client = await bff._client()
    try:
        await client.post(
            f"{bff._supabase_url()}/auth/v1/recover",
            json={"email": email},
            headers={"apikey": bff._anon_key(), "Content-Type": "application/json"},
        )
    except httpx.HTTPError:
        # Nessuna enumerazione account: la risposta resta identica anche
        # se Supabase non è raggiungibile in questo momento.
        pass
    return {
        "ok": True,
        "message": "Se l'email e' registrata riceverai un link di recupero.",
    }


@router.post("/reset")
async def reset_password(body: ResetPassword, request: Request):
    ip = _client_ip(request)
    await _check_account_throttle(ip)
    await throttle.record_event(_account_throttle_key(ip), _ACCOUNT_CHANGE_WINDOW)

    pwd = body.password
    if len(pwd) < _PASSWORD_MIN or not _SPECIAL_RE.search(pwd):
        raise HTTPException(
            422,
            f"La password deve avere almeno {_PASSWORD_MIN} caratteri "
            "e includere almeno un carattere speciale (es. ! @ # $ %)",
        )
    await _supabase_update_user(body.access_token, {"password": pwd})
    return {"ok": True, "message": "Password aggiornata, ora puoi accedere"}
