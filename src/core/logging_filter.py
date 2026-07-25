import logging
import re
from typing import Set

SAFE_KEYS: Set[str] = {
    "msg_id", "message_id",
    "org_id", "organization_id",
    "tenant_id",
    "timestamp",
    "event_type", "type",
    "status",
    "attempt_num", "attempt",
    "error_type",
    "duration_ms",
    "http_status", "status_code",
    "phone_number_id",
    "waba_id",
    "plan",
    "action",
    "pid",
}

_KEY_PATTERN = re.compile(r'(^|\s)([a-z_][a-z0-9_]*)=', re.IGNORECASE)


class PIIWhitelistFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if not msg.strip():
            return False
        keys_found = _KEY_PATTERN.findall(msg)
        if not keys_found:
            return False
        for _, key in keys_found:
            if key not in SAFE_KEYS:
                return False
        return True
