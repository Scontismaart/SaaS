"""Test per il check CI del tenant scoping (solo AST, nessun DB)."""
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_tenant_scoping.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_tenant_scoping", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_tenant_scoping = _load_script()
ALLOWLISTED_FUNCTIONS = check_tenant_scoping.ALLOWLISTED_FUNCTIONS
DEFAULT_TARGETS = check_tenant_scoping.DEFAULT_TARGETS
check_file = check_tenant_scoping.check_file
main = check_tenant_scoping.main

CLEAN_SOURCE = '''\
async def fetch_bookings(conn, org_id):
    return await conn.fetch(
        "SELECT * FROM bookings "
        "WHERE organization_id = $1",
        org_id,
    )


def health_probe(conn):
    return conn.fetchval("ping")
'''

BAD_SOURCE = '''\
async def fetch_booking_by_id(conn, booking_id):
    return await conn.fetchrow(
        "SELECT * FROM bookings WHERE id = $1",
        booking_id,
    )
'''


def _write_module(tmp_path: Path, code: str, name: str = "repo_mod.py") -> Path:
    path = tmp_path / name
    path.write_text(code, encoding="utf-8")
    return path


def test_clean_file_has_no_violations(tmp_path):
    path = _write_module(tmp_path, CLEAN_SOURCE)
    assert check_file(path) == []


def test_unscoped_select_on_tenant_table_is_flagged(tmp_path):
    path = _write_module(tmp_path, BAD_SOURCE)
    violations = check_file(path)
    assert len(violations) == 1
    label, fn_name, lineno, detail, sql = violations[0]
    assert label.endswith("repo_mod.py")
    assert fn_name == "fetch_booking_by_id"
    assert lineno == 1
    assert "bookings" in detail
    assert "bookings" in sql
    assert len(sql) <= 100


def test_system_scope_decorator_skips_function(tmp_path):
    source = (
        "from src.core.db.scoping import system_scope\n"
        "\n"
        "\n"
        '@system_scope("worker globale di retention")\n'
        "async def purge_old_messages(conn):\n"
        '    await conn.execute("DELETE FROM messages WHERE created_at < now()")\n'
    )
    path = _write_module(tmp_path, source)
    assert check_file(path) == []


def test_bare_system_scope_name_skips_function(tmp_path):
    source = (
        "@system_scope\n"
        "async def sweep_event_log(conn):\n"
        '    await conn.execute("DELETE FROM event_log")\n'
    )
    path = _write_module(tmp_path, source)
    assert check_file(path) == []


def test_allowlisted_function_is_skipped(tmp_path, monkeypatch):
    path = _write_module(tmp_path, BAD_SOURCE)
    monkeypatch.setitem(
        ALLOWLISTED_FUNCTIONS,
        f"{path.as_posix()}::fetch_booking_by_id",
        "motivo di test",
    )
    assert check_file(path) == []


def test_infra_and_root_tables_are_not_flagged(tmp_path):
    source = (
        "async def ping(conn):\n"
        '    return await conn.fetchval("SELECT 1")\n'
        "\n"
        "\n"
        "async def rename_org(conn, name, org_pk):\n"
        "    await conn.execute(\n"
        '        "UPDATE organizations SET name = $1 WHERE id = $2",\n'
        "        name,\n"
        "        org_pk,\n"
        "    )\n"
    )
    path = _write_module(tmp_path, source)
    assert check_file(path) == []


def test_dynamic_table_identifier_is_flagged(tmp_path):
    source = (
        "def load_rows(table):\n"
        '    return f"SELECT * FROM {table}"\n'
    )
    path = _write_module(tmp_path, source)
    violations = check_file(path)
    assert len(violations) == 1
    _, fn_name, lineno, detail, sql = violations[0]
    assert fn_name == "load_rows"
    assert lineno == 1
    assert detail == "dynamic table identifier"


def test_joinedstr_only_static_parts_count(tmp_path):
    source = (
        "async def count_open(conn, org_id):\n"
        "    return await conn.fetchval(\n"
        '        f"SELECT count(*) FROM conversations '
        'WHERE organization_id = {org_id}"\n'
        "    )\n"
        "\n"
        "\n"
        "async def count_all(conn, limit):\n"
        "    return await conn.fetchval(\n"
        '        f"SELECT count(*) FROM conversations LIMIT {limit}"\n'
        "    )\n"
    )
    path = _write_module(tmp_path, source)
    violations = check_file(path)
    assert len(violations) == 1
    _, fn_name, _, detail, sql = violations[0]
    assert fn_name == "count_all"
    assert "conversations" in detail
    assert detail != "dynamic table identifier"
    assert "conversations" in sql


def test_nested_function_reported_once_with_innermost_name(tmp_path):
    source = (
        "def weekly_cleanup():\n"
        "    async def run(conn):\n"
        '        await conn.execute("DELETE FROM faq_cache WHERE stale")\n'
        "\n"
        "    return run\n"
    )
    path = _write_module(tmp_path, source)
    violations = check_file(path)
    assert len(violations) == 1
    _, fn_name, _, detail, _sql = violations[0]
    assert fn_name == "run"
    assert "faq_cache" in detail


def test_main_returns_1_for_bad_file_and_0_for_clean(tmp_path):
    bad = _write_module(tmp_path, BAD_SOURCE, name="bad.py")
    clean = _write_module(tmp_path, CLEAN_SOURCE, name="clean.py")
    assert main(["check_tenant_scoping.py", str(bad)]) == 1
    assert main(["check_tenant_scoping.py", str(clean)]) == 0


def test_e2e_subprocess_bad_file_exits_1(tmp_path):
    bad = _write_module(tmp_path, BAD_SOURCE)
    proc = subprocess.run(
        [sys.executable, "scripts/check_tenant_scoping.py", str(bad)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "VIOLAZIONI" in proc.stdout
    assert "repo_mod.py" in proc.stdout


def test_e2e_subprocess_clean_file_exits_0(tmp_path):
    clean = _write_module(tmp_path, CLEAN_SOURCE)
    proc = subprocess.run(
        [sys.executable, "scripts/check_tenant_scoping.py", str(clean)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "TENANT SCOPING CHECK: OK" in proc.stdout
