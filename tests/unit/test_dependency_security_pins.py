"""Regression checks for dependency versions required by security advisories."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_weasyprint_pin_contains_ssrf_fix() -> None:
    """CVE-2026-55073 / GHSA-r543-q48m-4c9j is fixed in WeasyPrint 70."""
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    match = re.search(r"(?m)^weasyprint==(\d+)\.(\d+)(?:\.(\d+))?$", requirements)

    assert match, "WeasyPrint must remain exactly pinned"
    version = tuple(int(part or 0) for part in match.groups())
    assert version >= (70, 0, 0)


def test_torch_pin_is_cpu_only_for_release_images() -> None:
    """Oracle launch hosts have no GPU; CUDA wheels waste free-tier disk."""
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in requirements
    assert re.search(r"(?m)^torch==2\.14\.0\+cpu$", requirements)
