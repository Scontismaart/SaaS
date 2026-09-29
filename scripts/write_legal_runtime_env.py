#!/usr/bin/env python3
"""Create the web container's public-legal-only environment file.

The web container must not receive the API's full production environment. This
script copies only the reviewed public identity values needed by the legal
renderer and writes an owner-only file for compose's web service.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
from render_legal_pages import LEGAL_FIELDS, reviewed_values


def write_runtime_env(source: Path, output: Path) -> None:
    values = reviewed_values({key: value or "" for key, value in dotenv_values(source).items()})
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".next")
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            os.chmod(temporary, 0o600)
            for name in LEGAL_FIELDS:
                # dotenv output is parsed as literal values; reject line breaks
                # instead of creating an additional environment variable.
                if "\n" in values[name] or "\r" in values[name]:
                    raise ValueError(f"{name} cannot contain a line break")
                handle.write(f"{name}={values[name]}\n")
        os.replace(temporary, output)
        os.chmod(output, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file():
        parser.error("Environment file not found")
    write_runtime_env(args.env_file, args.output)


if __name__ == "__main__":
    main()
