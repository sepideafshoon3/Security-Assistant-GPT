import json
import os
from datetime import datetime
from pathlib import Path

DEFAULT_AUDIT_LOG = Path(
    os.getenv("AUDIT_LOG_PATH", "logs/actions-audit.log")
)


def audit_log(event_type: str, data: dict) -> None:
    DEFAULT_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": datetime.utcnow().isoformat() + "Z",
        "event": event_type,
        "data": data,
    }
    with DEFAULT_AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
