import os
import pickle
from typing import Optional
from google.oauth2.credentials import Credentials

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
_TOKENS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "gmail_tokens"
)


def _token_path(email: str) -> str:
    safe = email.replace("@", "_at_").replace(".", "_dot_")
    return os.path.join(_TOKENS_DIR, f"{safe}.token")


def load_credentials(email: str) -> Optional[Credentials]:
    path = _token_path(email)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        creds = pickle.load(f)
    if not isinstance(creds, Credentials):
        return None
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        try:
            creds.refresh(Request())
            save_credentials(email, creds)
        except Exception:
            return None
    return creds


def save_credentials(email: str, creds):
    os.makedirs(_TOKENS_DIR, exist_ok=True)
    with open(_token_path(email), "wb") as f:
        pickle.dump(creds, f)


def delete_credentials(email: str):
    path = _token_path(email)
    if os.path.exists(path):
        os.remove(path)


def authorize_new_account(client_secrets_file: str) -> tuple[str, Credentials]:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, _SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    email = profile["emailAddress"]

    save_credentials(email, creds)
    return email, creds


def list_authorized_accounts() -> list[str]:
    if not os.path.exists(_TOKENS_DIR):
        return []
    accounts = []
    for fname in os.listdir(_TOKENS_DIR):
        if not fname.endswith(".token"):
            continue
        email = fname[: -len(".token")]
        email = email.replace("_at_", "@").replace("_dot_", ".")
        accounts.append(email)
    return accounts


def get_service(email: str):
    from googleapiclient.discovery import build

    creds = load_credentials(email)
    if not creds:
        raise ValueError(
            f"Gmail non autorizzato per {email}. "
            "Usa POST /api/email/configura-gmail prima."
        )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
