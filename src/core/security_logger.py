import json
import logging
import os
from datetime import datetime, timezone

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_handler = logging.FileHandler(os.path.join(_LOG_DIR, "security-audit.log"), encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"))

_logger = logging.getLogger("security_audit")
_logger.propagate = False
_logger.addHandler(_handler)
_logger.setLevel(logging.INFO)


def security_audit(action: str, **fields):
    payload = {"action": action, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}
    _logger.info(json.dumps(payload, default=str))
