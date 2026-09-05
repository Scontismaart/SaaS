from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from fastapi import HTTPException, Request, Response

logger = logging.getLogger(__name__)

DEFAULT_MAX_BODY_SIZE = 5 * 1024 * 1024  # 5 MB
DEFAULT_TIMESTAMP_TOLERANCE = 300  # ±5 minuti


def _get_client_ip(request: Request) -> str:
    client = getattr(request, "client", None)
    if client is not None:
        host = getattr(client, "host", None)
        if isinstance(host, str):
            return host
    return "unknown"


def _get_path(request: Request) -> str:
    url = getattr(request, "url", None)
    if url is not None:
        path = getattr(url, "path", None)
        if isinstance(path, str):
            return path
    return ""


class MetaWebhookSecurity:
    """
    Standardized security layer for Meta webhooks (WhatsApp Cloud API & Instagram Graph API).
    Encapsulates:
    1. Hub Challenge verification (GET handshake)
    2. Replay protection via X-Timestamp header
    3. Streaming body size enforcement (DoS mitigation)
    4. HMAC-SHA256 signature verification with timing-attack prevention
    """

    def __init__(
        self,
        app_secret: str = "",
        verify_token: str = "",
        max_body_size: int = DEFAULT_MAX_BODY_SIZE,
        timestamp_tolerance: int = DEFAULT_TIMESTAMP_TOLERANCE,
    ):
        self.app_secret = app_secret
        self.verify_token = verify_token
        self.max_body_size = max_body_size
        self.timestamp_tolerance = timestamp_tolerance

    def verify_challenge(
        self,
        hub_mode: str | None,
        hub_verify_token: str | None,
        hub_challenge: str | None,
        override_token: str | None = None,
    ) -> Response:
        """Verifica l'handshake iniziale GET di Meta ('subscribe')."""
        token = override_token or self.verify_token
        if (
            hub_mode == "subscribe"
            and token
            and (hub_verify_token == token or hmac.compare_digest(hub_verify_token or "", token))
        ):
            return Response(content=hub_challenge or "challenge_ok", media_type="text/plain")
        raise HTTPException(status_code=403, detail="Verify token mismatch")

    def verify_timestamp(self, request: Request):
        """Verifica la presenza e la freschezza dell'header X-Timestamp se fornito."""
        timestamp_str = request.headers.get("X-Timestamp")
        if not timestamp_str:
            return

        client_ip = _get_client_ip(request)
        path = _get_path(request)
        try:
            ts = int(timestamp_str)
            now = time.time()
            if abs(now - ts) > self.timestamp_tolerance:
                logger.warning(
                    json.dumps({
                        "event": "webhook_timestamp_rejected",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "ip": client_ip,
                        "path": path,
                        "reason": f"timestamp {ts} out of tolerance {self.timestamp_tolerance}s",
                    })
                )
                raise HTTPException(status_code=403, detail="Timestamp out of tolerance")
        except ValueError:
            logger.warning(
                json.dumps({
                    "event": "webhook_timestamp_invalid",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "ip": client_ip,
                    "path": path,
                    "reason": f"non-integer timestamp: {timestamp_str}",
                })
            )
            raise HTTPException(status_code=400, detail="Invalid X-Timestamp")

    async def read_limited_body(self, request: Request) -> bytes:
        """Legge il body con limite streaming su max_body_size."""
        client_ip = _get_client_ip(request)
        path = _get_path(request)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_body_size:
            logger.warning(
                json.dumps({
                    "event": "webhook_body_oversize",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "ip": client_ip,
                    "path": path,
                    "reason": f"Content-Length {content_length} exceeds {self.max_body_size}",
                })
            )
            raise HTTPException(status_code=413, detail="Payload too large")

        chunks = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > self.max_body_size:
                logger.warning(
                    json.dumps({
                        "event": "webhook_body_oversize",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "ip": client_ip,
                        "path": path,
                        "reason": f"body exceeded {self.max_body_size} during streaming read",
                    })
                )
                raise HTTPException(status_code=413, detail="Payload too large")
            chunks.append(chunk)
        return b"".join(chunks)

    def verify_hmac(self, body: bytes, signature: str, secret: str | None = None) -> bool:
        """Verifica la firma HMAC-SHA256 con timing attack prevention."""
        sec = secret or self.app_secret
        if not sec:
            return False
        expected = hmac.new(sec.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature or "")

    async def authenticate_and_read(self, request: Request, override_secret: str | None = None) -> bytes:
        """Esegue la validazione di sicurezza completa per una richiesta POST webhook."""
        self.verify_timestamp(request)
        body = await self.read_limited_body(request)

        secret = override_secret or self.app_secret
        if secret and secret != "placeholder_meta_app_secret":
            signature = request.headers.get("X-Hub-Signature-256", "")
            if not self.verify_hmac(body, signature, secret):
                client_ip = _get_client_ip(request)
                path = _get_path(request)
                logger.warning(
                    json.dumps({
                        "event": "webhook_hmac_rejected",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "ip": client_ip,
                        "path": path,
                        "signature": signature,
                        "reason": "signature_mismatch",
                    })
                )
                raise HTTPException(status_code=403, detail="Invalid signature")

        return body
