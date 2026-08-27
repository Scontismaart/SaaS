"""Unit tests per Security Headers (CSP, X-Content-Type-Options, X-Frame-Options)
ed eliminazione del leakage di eccezioni interne nelle risposte HTTP.
"""

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from src.api.main import security_headers_middleware


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(security_headers_middleware)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/messaggio-mock")
    async def mock_message(fail: bool = False):
        if fail:
            # Simula errore 502 sanitizzato
            raise HTTPException(
                status_code=502,
                detail="Impossibile generare la risposta al momento. Riprova più tardi.",
            )
        return {"risposta": "ok"}

    @app.get("/api/report-mock")
    async def mock_report(fail: bool = False):
        if fail:
            raise HTTPException(
                status_code=502,
                detail="Impossibile generare il report. Riprova più tardi.",
            )
        return {"report": "ok"}

    return app


class TestSecurityHeadersMiddleware:
    def test_security_headers_present_on_response(self):
        app = _build_test_app()
        client = TestClient(app)

        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

        csp = resp.headers.get("content-security-policy")
        assert csp is not None
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "base-uri 'self'" in csp


class TestSanitizedErrorResponses:
    def test_message_error_response_sanitized(self):
        app = _build_test_app()
        client = TestClient(app)

        resp = client.post("/api/messaggio-mock?fail=true")
        assert resp.status_code == 502
        assert resp.json()["detail"] == "Impossibile generare la risposta al momento. Riprova più tardi."

    def test_report_error_response_sanitized(self):
        app = _build_test_app()
        client = TestClient(app)

        resp = client.get("/api/report-mock?fail=true")
        assert resp.status_code == 502
        assert resp.json()["detail"] == "Impossibile generare il report. Riprova più tardi."
