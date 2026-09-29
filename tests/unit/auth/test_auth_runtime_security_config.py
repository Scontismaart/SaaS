from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_api_container_disables_uvicorn_access_log():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    production_compose = (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    assert "--no-access-log" in dockerfile
    assert "--no-access-log" in production_compose


def test_caddy_access_logs_redact_auth_callback_query_values():
    sensitive_query_keys = (
        "code",
        "state",
        "error_description",
        "access_token",
        "refresh_token",
        "id_token",
        "code_verifier",
    )
    for name in ("Caddyfile.temporary", "Caddyfile.final"):
        config = (ROOT / name).read_text(encoding="utf-8")
        assert "request>uri query {" in config
        for key in sensitive_query_keys:
            assert f"replace {key} [redacted]" in config


def test_app_reload_revalidates_back_forward_cached_dashboard():
    source = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert 'window.addEventListener("pageshow"' in source
    assert "event.persisted" in source
    assert 'window.location.pathname.startsWith("/app/")' in source
    assert "window.location.reload()" in source
