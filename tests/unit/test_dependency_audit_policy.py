"""Reviewed residuals never authorize other versions or advisory IDs."""
import json
import runpy
from pathlib import Path

import pytest

AUDIT = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/check_dependency_audit.py"))


@pytest.mark.parametrize("version,advisory,expected", [
    ("3.5.0", "CVE-2026-85394", 0),
    ("3.5.1", "CVE-2026-85394", 1),
    ("3.4.0", "CVE-2026-85394", 1),
    ("3.5.0", "CVE-NEW-UNREVIEWED", 1),
])
def test_jose_residual_requires_exact_version_and_advisory(tmp_path, version, advisory, expected):
    dependencies = [{"name": f"clean-package-{n}", "version": "1.0", "vulns": []}
                    for n in range(50)]
    dependencies.append({"name": "python-jose", "version": version,
                         "vulns": [{"id": advisory}]})
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({"dependencies": dependencies}), encoding="utf-8")
    assert AUDIT["main"](str(report)) == expected


def test_jose_residual_has_no_broad_or_alias_exception():
    assert AUDIT["ACCEPTED"].get(("python-jose", "3.5.0")) == {"CVE-2026-85394"}


def test_incomplete_audit_still_fails_closed(tmp_path):
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({"dependencies": []}), encoding="utf-8")
    assert AUDIT["main"](str(report)) == 2
