from __future__ import annotations

import importlib.util
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from pathlib import Path

_SERVER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "serve_web.py"
_SPEC = importlib.util.spec_from_file_location("melpis_serve_web", _SERVER_PATH)
assert _SPEC and _SPEC.loader
_SERVER_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SERVER_MODULE)
DevHandler = _SERVER_MODULE.DevHandler


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), DevHandler)
    handler_errors = []

    def record_handler_error(_request, _client_address):
        handler_errors.append(sys.exc_info()[1])

    httpd.handle_error = record_handler_error
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        assert handler_errors == []


@pytest.mark.parametrize("route", ["/app/inbox", "/app/reviews", "/app/overview", "/app/settings", "/app/inbox/thread-123"])
def test_extensionless_dashboard_routes_serve_shell(server, route):
    with urlopen(server + route) as response:
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert "Melpis — Pannello di controllo" in body
        assert response.headers["Content-Type"].startswith("text/html")


def test_existing_dashboard_asset_is_served_as_asset(server):
    with urlopen(server + "/app/style.css") as response:
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("text/css")


def test_missing_extension_asset_is_not_rewritten_to_shell(server):
    with pytest.raises(HTTPError) as error:
        urlopen(server + "/app/missing.js")
    assert error.value.code == 404


@pytest.mark.parametrize("path", ["/app/%2e%2e/src/api/main.py", "/app/%2e%2e%2fsrc/api/main.py", "/app/%2e%2e%5csrc%5capi%5cmain.py"])
def test_dashboard_traversal_is_rejected(server, path):
    with pytest.raises(HTTPError) as error:
        urlopen(server + path)
    assert error.value.code in (403, 404)


@pytest.mark.parametrize("encoded_path", ["%FF", "%E0%80", "%C0%AF", "%E2%82"])
def test_malformed_dashboard_utf8_returns_controlled_error_and_server_remains_usable(server, encoded_path):
    with pytest.raises(HTTPError) as error:
        urlopen(server + "/app/" + encoded_path)
    assert error.value.code in (400, 404)

    with urlopen(server + "/app/settings?tab=account") as response:
        assert response.status == 200
        assert "Melpis — Pannello di controllo" in response.read().decode("utf-8")


def test_nginx_keeps_auth_gate_and_does_not_fallback_missing_assets_to_html():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    nginx = (root / "web" / "nginx.conf").read_text(encoding="utf-8")
    block = nginx.split("location ^~ /app/ {", 1)[1].split("\n    }", 1)[0]
    assert "wa_at=" in block
    assert 'return 302 "$auth_login_redirect?next=$uri#next=$request_uri";' in block
    assert "try_files $uri $uri/ @app_shell;" in block
    assert "location @app_shell" in nginx
    assert "if ($uri ~* \\.[^/]+$)" in nginx
    assert "rewrite ^ /app/index.html last;" in nginx


def test_router_is_wired_into_image_and_preview_mounts():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "web" / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "dashboard-router.js" in dockerfile
    assert "./web/dashboard-router.js:/usr/share/nginx/html/app/dashboard-router.js:ro" in compose
