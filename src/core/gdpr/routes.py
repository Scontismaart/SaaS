import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator

from src.core.auth.audit import audit_log
from src.core.auth.dependencies import require_ruolo, require_mfa
from src.core.db.repository import CoreRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gdpr", tags=["gdpr"])


# ── In-memory export token store ──────────────────────────────

_export_tokens: dict[str, dict] = {}


def _generate_export_token(org_id: str, data: dict) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    _export_tokens[token] = {"org_id": org_id, "data": data, "expires": expires}
    return token, expires


# ── Task 7: DPA template ──────────────────────────────────────

DPA_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Data Processing Agreement</title></head>
<body style="font-family:system-ui;max-width:800px;margin:2em auto;line-height:1.6">
<h1>Data Processing Agreement (DPA)</h1>
<p><strong>Last updated:</strong> July 2026</p>

<h2>1. Parties</h2>
<p><strong>Data Controller:</strong> The organization subscribing to the WhatsApp AI Responder service.</p>
<p><strong>Data Processor:</strong> WhatsApp AI Responder (the platform provider).</p>

<h2>2. Scope &amp; Purpose</h2>
<p>This DPA governs the processing of personal data by the Processor on behalf of the Controller in connection with the WhatsApp AI Responder service, including automated message handling, AI-driven responses, booking management, and customer communication.</p>

<h2>3. Categories of Data Processed</h2>
<ul>
  <li>Contact information: phone numbers, names</li>
  <li>Message content: text, timestamps, delivery status</li>
  <li>Conversation metadata: conversation history, interaction patterns</li>
  <li>Booking details: dates, times, party size, special requests</li>
  <li>Consent records: opt-in/opt-out status, timestamps</li>
</ul>

<h2>4. Sub-processors</h2>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
<tr><th>Sub-processor</th><th>Service</th><th>Data Location</th></tr>
<tr><td>Meta (WhatsApp Cloud API)</td><td>Message delivery</td><td>USA (Oregon, Virginia), Ireland (Dublin)</td></tr>
<tr><td>OpenRouter / LLM providers</td><td>AI response generation</td><td>USA (Oregon, Iowa), EU (Frankfurt, Stockholm)</td></tr>
<tr><td>Neon (Postgres hosting)</td><td>Database</td><td>USA (Ohio, Oregon), EU (Frankfurt)</td></tr>
<tr><td>Stripe</td><td>Payment processing</td><td>USA (multiple regions), Ireland (Dublin)</td></tr>
</table>

<h2>5. Data Retention</h2>
<p>Messages and conversation data are retained for a maximum of 90 days:</p>
<ul>
  <li>Day 60: automatic soft-delete (data invisible to the application)</li>
  <li>Day 90: permanent physical deletion</li>
</ul>
<p>Retention periods are configurable per tenant via the <code>message_retention_days</code> setting.</p>

<h2>6. Security Measures</h2>
<ul>
  <li>Encryption at rest: WhatsApp access tokens encrypted with Fernet (AES-128)</li>
  <li>PII redaction: strict whitelist-based log filtering</li>
  <li>Access control: role-based authentication (owner, manager, staff)</li>
  <li>Soft-delete: data recoverable within 30-day grace period</li>
</ul>

<h2>7. Data Subject Rights</h2>
<p>Controllers may exercise data subject rights via the GDPR API:</p>
<ul>
  <li><strong>Export:</strong> <code>GET /api/gdpr/export</code> — JSON export with 15-minute pre-signed URL</li>
  <li><strong>Deletion:</strong> <code>POST /api/gdpr/delete</code> — hard-delete with external service propagation</li>
  <li><strong>Consent:</strong> <code>GET/PUT /api/gdpr/consent-prefs</code> — manage consent preferences</li>
</ul>

<h2>8. Contact</h2>
<p>For DPA-related inquiries, contact the Data Protection Officer at: <strong>dpo@example.com</strong></p>
</body>
</html>"""


@router.get("/dpa", response_class=HTMLResponse)
async def get_dpa():
    return DPA_HTML


# ── Task 8: Consent preference center ─────────────────────────

class ConsentPrefsInput(BaseModel):
    phone_number: str
    consent_status: str

    @field_validator("consent_status")
    @classmethod
    def validate_status(cls, v):
        if v not in ("granted", "withdrawn", "unknown"):
            raise ValueError("consent_status must be 'granted', 'withdrawn', or 'unknown'")
        return v


class ConsentPrefsOutput(BaseModel):
    id: str
    phone_number: str
    consent_status: str | None
    consent_updated_at: str | None


@router.get("/consent-prefs")
async def get_consent_prefs(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    repo: CoreRepository = request.app.state.repo
    org_id = user["organization_id"]
    rows = await repo.get_contacts_by_org(org_id)
    result = []
    for row in rows:
        result.append(ConsentPrefsOutput(
            id=str(row["id"]),
            phone_number=row.get("phone_number", ""),
            consent_status=row.get("consent_status"),
            consent_updated_at=row["consent_updated_at"].isoformat() if row.get("consent_updated_at") else None,
        ))
    return result


@router.put("/consent-prefs")
async def update_consent_prefs(
    body: ConsentPrefsInput,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    repo: CoreRepository = request.app.state.repo
    org_id = user["organization_id"]

    from src.whatsapp.repository import Repository as WRepo
    wrepo = WRepo(pool=repo.pool)
    contact = await wrepo.get_or_create_contact(org_id, body.phone_number)

    event_type = "opt_in" if body.consent_status == "granted" else "opt_out" if body.consent_status == "withdrawn" else None
    if event_type:
        await wrepo.record_consent_event(contact["id"], event_type, "manual_staff")

    new_status = await wrepo.get_contact_consent(contact["id"])
    return {"phone_number": body.phone_number, "consent_status": new_status}


# ── Task 9: Data rights ────────────────────────────────────────

@router.get("/export")
async def gdpr_export(
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
    _mfa: dict = Depends(require_mfa()),
):
    repo: CoreRepository = request.app.state.repo
    org_id = user["organization_id"]
    data = await _export_tenant_data(repo, org_id)
    token, expires = _generate_export_token(str(org_id), data)
    download_url = str(request.base_url) + f"api/gdpr/download/{token}"

    await audit_log(repo, organization_id=org_id, action="gdpr.export",
                    auth_user_id=user.get("auth_user_id"),
                    details={"expires": expires.isoformat()})

    return {"download_url": download_url, "expires_in_minutes": 15}


@router.get("/download/{token}")
async def gdpr_download(token: str):
    if token not in _export_tokens:
        raise HTTPException(404, "Export token not found or expired")
    meta = _export_tokens[token]
    if datetime.now(timezone.utc) > meta["expires"]:
        del _export_tokens[token]
        raise HTTPException(410, "Export token expired")
    data = meta["data"]
    del _export_tokens[token]
    return data


@router.post("/delete")
async def gdpr_delete(
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
    _mfa: dict = Depends(require_mfa()),
):
    from src.core.gdpr.propagation import propagate_hard_delete

    repo: CoreRepository = request.app.state.repo
    org_id = user["organization_id"]

    propagation_results = await propagate_hard_delete(str(org_id))

    await audit_log(repo, organization_id=org_id, action="gdpr.hard_delete",
                    auth_user_id=user.get("auth_user_id"),
                    details={"propagation": propagation_results})

    await repo.delete_organization(org_id)

    return {
        "status": "deleted",
        "propagation": propagation_results,
        "message": "All data permanently removed. External services notified.",
    }


@router.get("/retention-policy")
async def retention_policy():
    return {"retention_days": 60, "purge_after_days": 30}


async def _export_tenant_data(repo: CoreRepository, org_id: str) -> dict:
    contacts = await repo.get_contacts_by_org(org_id)
    conversations = await repo.get_conversations_by_org(org_id)
    messages = await repo.get_messages_by_org(org_id)

    return {
        "organization_id": str(org_id),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "contacts": [
            {"id": str(c["id"]), "phone": c.get("phone_number"), "consent_status": c.get("consent_status")}
            for c in contacts
        ],
        "conversations": [
            {"id": str(c["id"]), "created_at": c.get("created_at").isoformat() if c.get("created_at") else None}
            for c in conversations
        ],
        "messages": [
            {
                "id": str(m["id"]),
                "direction": m.get("direction"),
                "message_type": m.get("message_type"),
                "content_text": m.get("content_text"),
                "created_at": m.get("created_at").isoformat() if m.get("created_at") else None,
            }
            for m in messages
        ],
    }
