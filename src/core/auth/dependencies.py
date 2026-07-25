import os
import time
import httpx
from typing import Any
from fastapi import Header, HTTPException, Depends, Request


JWT_ALGORITHM = "RS256"
JWKS_CACHE: dict[str, Any] = {"keys": None, "expires_at": 0}
HTTP_CLIENT: httpx.AsyncClient | None = None
VALID_RUOLI = {"owner", "manager", "staff", "service_role"}


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
    for key in jwks:
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[Algorithms.RS256],
                audience=expected_aud,
                options={"verify_aud": True},
            )
            return payload
        except JWTError:
            continue
    raise HTTPException(403, "Token JWT non valido")


async def get_token(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> str:
    if authorization:
        return authorization.removeprefix("Bearer ")
    if x_api_key:
        return f"apikey:{x_api_key}"
    raise HTTPException(status_code=401, detail="Token o API Key richiesti")


async def get_current_user(token: str = Depends(get_token)) -> dict:
    if token.startswith("apikey:"):
        key = token.removeprefix("apikey:")
        if key != os.getenv("API_KEY_SERVICE"):
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
    if current_user["source"] == "api_key":
        return {**current_user, "organization_id": x_organization_id}
    if not x_organization_id:
        return current_user
    # repo risolto qui (non come Depends) cosi' il path api_key sopra non
    # forza mai la presenza del repository: prima il bug faceva rispondere
    # 500 "Repository non inizializzato" pure con API key valida quando
    # DATABASE_URL non e' configurato (demo mode).
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
        if user.get("source") == "api_key":
            return user
        if user.get("ruolo") not in ruoli:
            raise HTTPException(
                403, f"Richiesto ruolo: {', '.join(ruoli)}"
            )
        return user
    return _check
