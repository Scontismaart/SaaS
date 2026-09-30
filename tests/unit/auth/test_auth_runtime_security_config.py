from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_api_container_disables_uvicorn_access_log():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    production_compose = (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    local_compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    docker_cmd = next(line for line in dockerfile.splitlines() if line.startswith('CMD ["uvicorn"'))
    production_cmd = next(line for line in production_compose.splitlines() if "command: [uvicorn" in line)
    local_cmd = next(line for line in local_compose.splitlines() if "command: [uvicorn" in line)
    local_readme_cmd = next(line for line in readme.splitlines() if "Esecuzione locale:" in line)

    assert all(
        "--no-access-log" in command
        for command in (docker_cmd, production_cmd, local_cmd, local_readme_cmd)
    )


def test_caddy_access_logs_redact_auth_callback_query_values():
    sensitive_headers = (
        "Cookie",
        "Referer",
        "Set-Cookie",
        "Location",
        "Authorization",
        "Proxy-Authorization",
        "X-API-Key",
        "X-CSRF-Token",
    )
    for name in ("Caddyfile.temporary", "Caddyfile.final"):
        config = (ROOT / name).read_text(encoding="utf-8")
        assert "request>uri regexp `\\?.*$` `?[QUERY REDACTED]`" in config
        for header in sensitive_headers:
            if header in {"Set-Cookie", "Location"}:
                assert f"resp_headers>{header} delete" in config
                assert f"request>headers>{header} delete" not in config
                continue
            assert f"request>headers>{header} delete" in config


def test_app_reload_revalidates_back_forward_cached_dashboard():
    source = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert 'window.addEventListener("pageshow"' in source
    assert "event.persisted" in source
    assert 'window.location.pathname.startsWith("/app/")' in source
    assert "window.location.reload()" in source
