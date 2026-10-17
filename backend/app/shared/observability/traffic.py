"""Development-only, in-memory traffic trace for HTTP and WebSocket flows.

Payload contents and query strings are intentionally never stored. The trace is
small, process-local, and disappears when the backend restarts.
"""

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any
import json
import uuid


_MAX_EVENTS = 500
_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_events_lock = Lock()


def _payload_metadata(payload: Any) -> tuple[list[str], int]:
    if isinstance(payload, dict):
        keys = sorted(str(key)[:64] for key in payload.keys())[:32]
    else:
        keys = []
    try:
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    except (TypeError, ValueError):
        size = 0
    return keys, size


def record_traffic_event(
    *,
    kind: str,
    direction: str,
    name: str,
    method: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    duration_ms: float | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    message_type: str | None = None,
    payload: Any = None,
    error: str | None = None,
) -> None:
    """Append metadata about one request/message without retaining its contents."""
    payload_keys, payload_bytes = _payload_metadata(payload) if payload is not None else ([], 0)
    event: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "kind": kind,
        "direction": direction,
        "name": name,
    }
    optional = {
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
        "trace_id": trace_id,
        "session_id": session_id,
        "message_type": message_type,
        "payload_keys": payload_keys,
        "payload_bytes": payload_bytes,
        "error": error[:160] if error else None,
    }
    event.update({key: value for key, value in optional.items() if value is not None})
    with _events_lock:
        _events.append(event)


def get_traffic_events(limit: int = 100) -> list[dict[str, Any]]:
    """Return the latest events, newest first, with a bounded result size."""
    safe_limit = max(1, min(int(limit), _MAX_EVENTS))
    with _events_lock:
        return list(reversed(list(_events)[-safe_limit:]))


def clear_traffic_events() -> int:
    """Clear the in-memory trace and return the number of removed records."""
    with _events_lock:
        count = len(_events)
        _events.clear()
    return count
