import hmac
import os
import time
import httpx
from pathlib import Path
from typing import Any
from fastapi import Header, HTTPException, Depends, Request
from typing import Optional
from dotenv import load_dotenv


JWT_ALGORITHM = "RS256"
JWKS_CACHE: dict[str, Any] = {"keys": None, "expires_at": 0}
HTTP_CLIENT: httpx.AsyncClient | None = None
VALID_RUOLI = {"owner", "manager", "staff", "service_role"}
ENV_LOADED = False


def _load_project_env() -> None:
    global ENV_LOADED
    if ENV_LOADED:
        return
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env", override=False)
    ENV_LOADED = True


def is_demo_mode() -> bool:
    _load_project_env()
    return os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")


async def get_http_client() -> httpx.AsyncClient:
    global HTTP_CLIENT
    if HTTP_CLIENT is None:
        HTTP_CLIENT = httpx.AsyncClient(timeout=10.0)
    return HTTP_CLIENT


async def close_http_client():
    global HTTP_CLIENT
    if HTTP_CLIENT is not None:
        await HTTP_CLIENT.aclose()
        HTTP_CLIENT = None


async def _get_supabase_jwks() -> list[dict]:
    supabase_url = os.getenv("SUPABASE_URL")
    if not supabase_url:
        raise HTTPException(500, "SUPABASE_URL non configurato")
    now = time.time()
    if JWKS_CACHE["keys"] and now < JWKS_CACHE["expires_at"]:
        return JWKS_CACHE["keys"]
    client = await get_http_client()
    resp = await client.get(f"{supabase_url}/auth/v1/.well-known/jwks.json")
    resp.raise_for_status()
    data = resp.json()
    JWKS_CACHE["keys"] = data["keys"]
    JWKS_CACHE["expires_at"] = now + 300
    return JWKS_CACHE["keys"]


async def verify_supabase_jwt(token: str) -> dict:
    from jose import jwt, JWTError
    from jose.constants import Algorithms

    jwks = await _get_supabase_jwks()
    expected_aud = os.getenv("SUPABASE_JWT_AUD", "authenticated")
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    # Audit 1.4: senza verifica iss, un JWT valido firmato da un progetto
    # Supabase diverso ma con stessa audience "authenticated" verrebbe
    # comunque accettato. L'issuer atteso e' sempre "<SUPABASE_URL>/auth/v1".
    expected_iss = f"{supabase_url}/auth/v1" if supabase_url else None
    for key in jwks:
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[Algorithms.RS256],
                audience=expected_aud,
                issuer=expected_iss,
                options={"verify_aud": True, "verify_iss": bool(expected_iss)},
            )
            return payload
        except JWTError:
            continue
    raise HTTPException(403, "Token JWT non valido")


async def get_token(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> Optional[str]:
    if authorization:
        return authorization.removeprefix("Bearer ")
    if x_api_key:
        return f"apikey:{x_api_key}"
    return None


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(get_token),
) -> dict:
    if token is None:
        if not is_demo_mode():
            raise HTTPException(status_code=401, detail="Token o API Key richiesti")
        return {
            "auth_user_id": None,
            "organization_id": None,
            "ruolo": None,
            "source": "anonymous",
        }
    if token.startswith("apikey:"):
        key = token.removeprefix("apikey:")
        expected = os.getenv("API_KEY_SERVICE") or ""
        # Audit 1.5: confronto con == e' vulnerabile a timing attack (il
        # tempo di confronto rivela quanti caratteri iniziali coincidono).
        # hmac.compare_digest confronta in tempo costante.
        if not expected or not hmac.compare_digest(key, expected):
            raise HTTPException(status_code=403, detail="API Key non valida")
        return {
            "auth_user_id": None,
            "organization_id": None,
            "ruolo": "service_role",
            "source": "api_key",
        }
    payload = await verify_supabase_jwt(token)
    return {
        "auth_user_id": payload["sub"],
        "organization_id": None,
        "ruolo": None,
        "source": "jwt",
        # Audit 1.4: aal (authenticator assurance level) serve per il gate
        # MFA sui Tier-1 sensibili (billing, GDPR hard-delete/export). Lo
        # estraiamo dal JWT qui, una sola volta, e require_mfa lo legge dal
        # dict utente: evita di rivalutare il claim su ogni endpoint.
        "aal": payload.get("aal"),
    }


def get_repo(request: Request):
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(500, "Repository non inizializzato")
    return repo


async def get_organization_context(
    request: Request,
    current_user: dict = Depends(get_current_user),
    x_organization_id: str | None = Header(None),
) -> dict:
    if current_user["source"] in ("api_key", "anonymous"):
        return {**current_user, "organization_id": x_organization_id}
    if not x_organization_id:
        return current_user
    repo = get_repo(request)
    membership = await repo.get_membership_by_auth(
        current_user["auth_user_id"], x_organization_id
    )
    if not membership:
        raise HTTPException(403, "Non sei membro di questa organizzazione")
    return {
        **current_user,
        "organization_id": x_organization_id,
        "ruolo": membership["ruolo"],
    }


def require_ruolo(*ruoli: str):
    invalid = set(ruoli) - VALID_RUOLI
    if invalid:
        raise ValueError(f"Ruoli non validi: {invalid}. Validi: {VALID_RUOLI}")
    async def _check(user: dict = Depends(get_organization_context)):
        if user.get("source") in ("api_key", "anonymous"):
            return user
        if user.get("ruolo") not in ruoli:
            raise HTTPException(
                403, f"Richiesto ruolo: {', '.join(ruoli)}"
            )
        return user
    return _check


# Audit 1.4: endpoint "sensibili" (Tier-1) che richiedono step-up a MFA.
# Operazioni irreversibili, finanziarie o di esfiltrazione PII: l'uso di una
# sessione rubata (cookie/JSON rubato) deve comunque bloccarsi se l'utente
# non ha fatto il secondo fattore. La lista va tenuta corta di proposito:
# ogni endpoint qui aggiunto rende il prodotto meno usabile da mobile, dove
# il titolare gestisce le urgenze HITL. Per questo HITL reply, booking,
# documenti NON sono in questa lista.
SENSITIVE_AAL2_PATHS = frozenset({
    "/api/billing/create-checkout-session",
    "/api/billing/create-portal-session",
    "/api/gdpr/export",
    "/api/gdpr/delete",
    "/api/calendar/auth",
    "/api/calendar/disconnect",
    "/api/calendar/settings",
    "/api/reviews/google/auth",
    "/api/reviews/google/settings",
    "/api/reviews/google/disconnect",
})


def require_mfa():
    """Dipendenza da combinare DOPO require_ruolo sui Tier-1.

    Esempio:
        user = Depends(require_ruolo("owner"))
        mfa  = Depends(require_mfa())

    Le richieste via API_KEY_SERVICE (source="api_key") sono esenti: sono
    credenziali interne al backend (inbound processor, webhook Stripe) e non
    rappresentano una sessione utente rubabile.
    """
    async def _check(user: dict = Depends(get_current_user)):
        if user.get("source") == "api_key":
            return user
        # aal: Supabase popola "aal2" solo dopo verifica del secondo fattore.
        # Token legacy o sessioni senza MFA portano aal=None o "aal1".
        if user.get("aal") != "aal2":
            raise HTTPException(
                status_code=403,
                detail="Autenticazione a due fattori (MFA) richiesta per questa operazione. "
                       "Abilitala in Impostazioni > Sicurezza e riprova.",
                headers={"X-MFA-Required": "true"},
            )
        return user
    return _check
