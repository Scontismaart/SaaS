import pytest

try:
    from src.api.main import app
    HAS_MAIN = True
except ImportError as e:
    HAS_MAIN = False
    _import_error = str(e)


@pytest.mark.skipif(not HAS_MAIN, reason=f"Cannot import main.py: {globals().get('_import_error', 'unknown')}")
def test_health_check():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
