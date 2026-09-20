"""Static release-container checks that do not require Docker or network access."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _job(workflow: str, name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"missing workflow job: {name}"
    return match.group("body")


def _compose_service(compose: str, name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|^networks:\n|^volumes:\n|\Z)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"missing compose service: {name}"
    return match.group("body")


def test_validation_gates_all_image_builds_and_prs_never_publish() -> None:
    workflow = _read(".github/workflows/ci.yml")
    validation = _job(workflow, "test")
    build = _job(workflow, "build_images")
    publish = _job(workflow, "publish_images")

    for expected in (
        "ruff check",
        "npm run lint:web",
        "npm run test:web",
        "python scripts/check_tenant_scoping.py",
        "pytest -v --tb=short",
        "docker compose",
        "test_oracle_vm_bootstrap.sh",
    ):
        assert expected in validation

    assert "needs: test" in build
    assert "needs: test" in publish
    assert "github.event_name == 'pull_request'" in build
    assert "push: false" in build
    assert "docker/login-action" not in build

    assert "github.event_name == 'push'" in publish
    assert "github.ref == 'refs/heads/main'" in publish
    assert "permissions:" in publish
    assert "packages: write" in publish
    assert "docker/login-action" in publish
    assert "push: true" in publish


def test_buildx_builds_api_and_web_for_amd64_and_arm64_with_sha_only_tags() -> None:
    workflow = _read(".github/workflows/ci.yml")

    for job_name in ("build_images", "publish_images"):
        job = _job(workflow, job_name)
        assert "docker/setup-qemu-action" in job
        assert "docker/setup-buildx-action" in job
        assert "docker/build-push-action" in job
        assert "linux/amd64,linux/arm64" in job
        assert "./Dockerfile" in job
        assert "./web/Dockerfile" in job
        assert "context: ." in job
        assert "context: ./web" in job

    publish = _job(workflow, "publish_images")
    assert ":sha-${{ github.sha }}" in publish
    assert ":latest" not in workflow
    assert "type=ref" not in publish


def test_production_compose_uses_release_images_and_only_caddy_publishes() -> None:
    compose = _read("compose.production.yml")
    assert "${MELPIS_API_IMAGE_REF:-" in compose
    assert "${MELPIS_WEB_IMAGE_REF:-" in compose
    assert "${MELPIS_API_IMAGE:?" in compose
    assert "${MELPIS_WEB_IMAGE:?" in compose
    assert compose.count("${MELPIS_IMAGE_TAG:?") == 2
    assert ":latest" not in compose
    assert "build:" not in compose

    services = ("caddy", "web", "api", "worker-inbound", "worker-retry", "supervisor", "valkey")
    assert 'ports: ["80:80", "443:443"]' in _compose_service(compose, "caddy")
    for service in services[1:]:
        assert "ports:" not in _compose_service(compose, service)


def test_caddy_supports_temporary_tls_and_final_canonical_hosts() -> None:
    caddyfile = _read("Caddyfile")
    assert "{$PUBLIC_HOST:localhost}" in caddyfile
    assert "melpis.it" in caddyfile
    assert re.search(
        r"app\.melpis\.it\s*\{.*?redir\s+https://melpis\.it/app/\s+308.*?\}",
        caddyfile,
        flags=re.DOTALL,
    )
    assert "reverse_proxy @backend api:8000" in caddyfile
    assert "reverse_proxy web:80" in caddyfile


def test_application_dockerfiles_are_architecture_neutral() -> None:
    for relative_path in ("Dockerfile", "web/Dockerfile"):
        dockerfile = _read(relative_path)
        assert "--platform=linux/amd64" not in dockerfile
        assert "--platform=linux/arm64" not in dockerfile
        assert "TARGETARCH=amd64" not in dockerfile
