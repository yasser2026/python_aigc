"""Debug session NDJSON logging (agent instrumentation)."""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.config_loader import get_root

_LOG_NAME = "debug-dee341.log"
_SESSION = "dee341"


def agent_log(
    location: str,
    message: str,
    data: dict[str, Any],
    hypothesis_id: str,
    run_id: str = "pre-fix",
) -> None:
    # #region agent log
    payload = {
        "sessionId": _SESSION,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
        "hypothesisId": hypothesis_id,
        "runId": run_id,
    }
    path = get_root() / _LOG_NAME
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    # #endregion
