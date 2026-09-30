"""Exercise Uvicorn itself, not a manually constructed logging record."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
CODE_CANARY = "SYNTHETIC_REAL_UVICORN_CODE"
STATE_CANARY = "SYNTHETIC_STATE"
ERROR_PROBE = "SYNTHETIC_ERROR_LOG_PROBE"


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_real_uvicorn(*, no_access_log: bool, app_guard: bool) -> str:
    port = _available_port()
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = os.pathsep.join((str(FIXTURES), str(ROOT)))
    child_env["PYTHON_DOTENV_DISABLED"] = "true"
    child_env["MELPIS_PROBE_APP_GUARD"] = "1" if app_guard else "0"
    command = [
        sys.executable, "-m", "uvicorn", "uvicorn_logging_probe:app",
        "--host", "127.0.0.1", "--port", str(port), "--no-proxy-headers",
    ]
    if no_access_log:
        command.append("--no-access-log")

    process = subprocess.Popen(
        command, cwd=ROOT, env=child_env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    output = ""
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError("Uvicorn probe exited before it was ready")
            try:
                with urlopen(f"http://127.0.0.1:{port}/ready", timeout=0.5):
                    break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            raise AssertionError("Uvicorn probe did not become ready")

        callback = (
            f"http://127.0.0.1:{port}/api/auth/google/callback"
            f"?code={CODE_CANARY}&state={STATE_CANARY}"
        )
        with urlopen(callback, timeout=2) as response:
            assert response.status == 204
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate(timeout=5)
    return output


def test_real_uvicorn_access_logger_is_disabled_and_errors_survive():
    raw_output = _run_real_uvicorn(no_access_log=False, app_guard=False)
    assert CODE_CANARY in raw_output
    assert STATE_CANARY in raw_output

    for no_access_log, app_guard in ((True, False), (False, True)):
        safe_output = _run_real_uvicorn(
            no_access_log=no_access_log, app_guard=app_guard
        )
        canary_leaked = CODE_CANARY in safe_output or STATE_CANARY in safe_output
        access_record_present = "GET /api/auth/google/callback" in safe_output
        error_log_present = ERROR_PROBE in safe_output
        assert not canary_leaked
        assert not access_record_present
        assert error_log_present
