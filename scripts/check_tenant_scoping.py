#!/usr/bin/env python3
"""Check CI anti-bypass del tenant scoping (Invariante #1: Tenant Isolation).

Scansione statica (AST) dei file repository-layer: segnala ogni SQL
letterale su tabelle tenant-scoped senza filtro organization_id esplicito,
piu' le f-string che interpolano l'identificatore della tabella. Condivide
le primitive di src.core.db.scoping (unica fonte di verita').

Uso:
    python scripts/check_tenant_scoping.py [file ...]

Senza argomenti controlla DEFAULT_TARGETS. Exit 0 = OK, exit 1 = violazioni.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.db.scoping import TENANT_SCOPED_TABLES, extract_tables

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TARGETS = [
    "src/whatsapp/repository.py",
    "src/core/db/repository.py",
    "src/instagram/repository.py",
    "src/core/billing/webhook_handler.py",
    "src/core/bookings/reminder_job.py",
    "src/core/calendar/service.py",
    "src/core/report/weekly_report.py",
]

# Eccezioni revisionate a mano: chiave "{percorso}::{funzione}", valore =
# motivo obbligatorio. Aggiungere SOLO dopo aver verificato che l'accesso
# cross-tenant sia intenzionale; ogni voce appare nella reportistica CI.
ALLOWLISTED_FUNCTIONS: dict[str, str] = {}

_SQL_KEYWORD_RE = re.compile(r"\b(select|insert|update|delete)\b", re.IGNORECASE)
_DYNAMIC_TABLE_RE = re.compile(r"(?:from|join|into|update)\s*$", re.IGNORECASE)

_DYNAMIC_TABLE_DETAIL = "dynamic table identifier"


def _path_label(path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _is_system_scope(fn) -> bool:
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name) and target.id == "system_scope":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "system_scope":
            return True
    return False


def _string_parts(node):
    """(parti_statiche, interpolata) o None se il nodo non e' una stringa.

    Le parti statiche sono i soli ast.Constant testuali; FormattedValue
    non contribuisce nulla al testo analizzabile.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return [node.value], False
        return None
    if isinstance(node, ast.JoinedStr):
        parts = [
            v.value
            for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
        return parts, True
    return None


class _Visitor(ast.NodeVisitor):
    """Attribuisce ogni letterale SQL alla funzione piu' interna."""

    def __init__(self, label: str, violations: list, seen: set):
        self._label = label
        self._violations = violations
        self._seen = seen
        self._stack: list[tuple] = []

    def visit_FunctionDef(self, node):
        exempt = _is_system_scope(node)
        exempt = exempt or (
            f"{self._label}::{node.name}" in ALLOWLISTED_FUNCTIONS
        )
        self._stack.append((node, exempt))
        self.generic_visit(node)
        self._stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_JoinedStr(self, node):
        self._handle_string(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            self._handle_string(node)

    def _add(self, fn, detail: str, sql: str) -> None:
        key = (fn.name, fn.lineno)
        if key in self._seen:
            return
        self._seen.add(key)
        self._violations.append(
            (self._label, fn.name, fn.lineno, detail, sql[:100])
        )

    def _handle_string(self, node) -> None:
        if not self._stack:
            return
        parsed = _string_parts(node)
        if parsed is None:
            return
        parts, interpolated = parsed
        static = "".join(parts)
        if not _SQL_KEYWORD_RE.search(static):
            return
        fn, exempt = self._stack[-1]
        if exempt:
            return
        if interpolated and any(_DYNAMIC_TABLE_RE.search(p) for p in parts):
            self._add(fn, _DYNAMIC_TABLE_DETAIL, static)
            return
        tables = extract_tables(static) & TENANT_SCOPED_TABLES
        if tables and "organization_id" not in static:
            self._add(fn, ", ".join(sorted(tables)), static)


def check_file(path) -> list[tuple]:
    """Violazioni [(percorso, funzione, riga, dettaglio, sql), ...] del file."""
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    violations: list[tuple] = []
    seen: set[tuple[str, int]] = set()
    _Visitor(_path_label(path), violations, seen).visit(tree)
    return violations


def main(argv) -> int:
    targets = argv[1:] or DEFAULT_TARGETS
    violations: list[tuple] = []
    checked = 0
    for target in targets:
        path = Path(target)
        if not path.exists():
            print(f"TENANT SCOPING CHECK: file mancante: {target}", file=sys.stderr)
            return 2
        violations.extend(check_file(path))
        checked += 1
    if violations:
        print(f"TENANT SCOPING CHECK: {len(violations)} VIOLAZIONI\n")
        for path, fn_name, lineno, detail, sql in violations:
            print(f"  {path}:{lineno}  {fn_name}()  ->  {detail}")
            print(f"      {sql!r}")
        print(f"\nFile controllati: {checked}")
        return 1
    print("TENANT SCOPING CHECK: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
