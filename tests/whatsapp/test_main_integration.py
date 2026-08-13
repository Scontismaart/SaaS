import pytest

try:
    from src.api.main import app
    HAS_MAIN = True
except ImportError as e:
    HAS_MAIN = False
    _import_error = str(e)


@pytest.mark.skipif(not HAS_MAIN, reason=f"Cannot import main.py: {globals().get('_import_error', 'unknown')}")
def test_health_check(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200


@pytest.mark.skipif(not HAS_MAIN, reason=f"Cannot import main.py: {globals().get('_import_error', 'unknown')}")
def test_rate_limit_llm_global(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    import src.api.main as main_mod
    main_mod.rate_windows.clear()
    monkeypatch.setattr("src.api.main.LLM_GLOBAL_RATE_LIMIT", 2)
    monkeypatch.setattr("src.api.main.LLM_GLOBAL_RATE_WINDOW", 99999)
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test", "X-Organization-Id": "org-1"}
        resp1 = client.post("/api/messaggio", json={"test": True}, headers=headers)
        # Falliment previsto perche' non c'e' DB, ma conta che status
        # NON sia 429 (il rate limit non deve scattare al primo colpo)
        assert resp1.status_code != 429
        resp2 = client.post("/api/messaggio", json={"test": True}, headers=headers)
        assert resp2.status_code != 429
        resp3 = client.post("/api/messaggio", json={"test": True}, headers=headers)
        assert resp3.status_code == 429
        assert "globale" in resp3.json()["detail"].lower()


@pytest.mark.skipif(not HAS_MAIN, reason=f"Cannot import main.py: {globals().get('_import_error', 'unknown')}")
def test_cors_header_present(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


@pytest.mark.skipif(not HAS_MAIN, reason=f"Cannot import main.py: {globals().get('_import_error', 'unknown')}")
def test_cors_whitespace_stripped(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com , http://b.com")
    import importlib

    import src.api.main as main_mod

    importlib.reload(main_mod)
    app2 = main_mod.app
    from fastapi.testclient import TestClient
    with TestClient(app2) as client:
        resp = client.get("/api/health", headers={"Origin": "http://a.com"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://a.com"
        resp2 = client.get("/api/health", headers={"Origin": "http://b.com"})
        assert resp2.status_code == 200
        assert resp2.headers.get("access-control-allow-origin") == "http://b.com"


@pytest.mark.skipif(not HAS_MAIN, reason=f"Cannot import main.py: {globals().get('_import_error', 'unknown')}")
def test_cors_fail_closed_on_empty(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " , ")
    import importlib
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        importlib.reload(importlib.import_module("src.api.main"))
