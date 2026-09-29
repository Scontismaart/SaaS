#!/usr/bin/env python3
"""Render reviewed public legal templates into a writable runtime directory.

Only the six explicitly allowlisted LEGAL_* identity fields are read.  This is
intentionally not a general environment substitution facility: a secret added
to the container environment can never be interpolated into public HTML.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
from pathlib import Path


LEGAL_FIELDS = (
    "LEGAL_ENTITY_NAME",
    "LEGAL_ENTITY_REGISTERED_OFFICE",
    "LEGAL_ENTITY_VAT_NUMBER",
    "LEGAL_PRIVACY_CONTACT_EMAIL",
    "LEGAL_FORUM",
    "LEGAL_DOCUMENT_EFFECTIVE_DATE",
)
LEGAL_TOKEN = re.compile(r"\{\{LEGAL_[A-Z_]+\}\}")
PLACEHOLDER_MARKERS = ("<", ">", "placeholder", "replace-me", "example", "dummy")
TEMPLATE_PATHS = (
    "privacy.html",
    "termini.html",
    "cookie.html",
    "en/privacy/index.html",
    "en/terms/index.html",
    "en/cookies/index.html",
    "es/privacidad/index.html",
    "es/terminos/index.html",
    "es/cookies/index.html",
    "fr/confidentialite/index.html",
    "fr/conditions/index.html",
    "fr/cookies/index.html",
    "de/datenschutz/index.html",
    "de/agb/index.html",
    "de/cookies/index.html",
)


def reviewed_values(environ: dict[str, str]) -> dict[str, str]:
    """Return only complete, non-placeholder values approved for public copy."""
    values: dict[str, str] = {}
    for name in LEGAL_FIELDS:
        value = environ.get(name, "").strip()
        if not value or any(marker in value.lower() for marker in PLACEHOLDER_MARKERS):
            raise ValueError(f"{name} is missing or a placeholder")
        values[name] = value
    return values


def render(template: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", html.escape(value, quote=True))
    unresolved = LEGAL_TOKEN.findall(template)
    if unresolved:
        raise ValueError("unresolved public legal token(s): " + ", ".join(sorted(set(unresolved))))
    return template


def render_tree(template_dir: Path, output_dir: Path, environ: dict[str, str]) -> None:
    values = reviewed_values(environ)
    staging_dir = output_dir.with_name(output_dir.name + ".next")
    shutil.rmtree(staging_dir, ignore_errors=True)
    try:
        for relative in TEMPLATE_PATHS:
            source = template_dir / relative
            if not source.is_file():
                raise ValueError(f"legal template missing: {relative}")
            destination = staging_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(render(source.read_text(encoding="utf-8"), values), encoding="utf-8")
        shutil.rmtree(output_dir, ignore_errors=True)
        staging_dir.replace(output_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    render_tree(args.template_dir, args.output_dir, dict(os.environ))


if __name__ == "__main__":
    main()
