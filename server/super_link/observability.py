"""Process-local counters for Super-link SSE health.

The database remains the source of truth; these counters only make connection,
preview and notification pressure observable for a single API owner.  They are
deliberately not persisted and not exported to another process: the first
version runs one Super-link owner, and a second instance must not imply that
these numbers are cluster-wide.
"""

from __future__ import annotations

import threading
from typing import Any

_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = {
    "sse.opened": 0,
    "sse.closed": 0,
    "sse.rejected": 0,
    "sse.slow_closed": 0,
    "sse.auth_revoked": 0,
    "sse.max_age_closed": 0,
    "sse.active_total": 0,
    "preview.frames": 0,
    "preview.resets": 0,
    "preview.dropped": 0,
    "notifier.published": 0,
    "notifier.failed": 0,
}


def inc(key: str, amount: int = 1) -> None:
    """Add to one counter; unknown keys are ignored so call sites stay cheap."""
    if key not in _COUNTERS:
        return
    with _LOCK:
        _COUNTERS[key] += amount


def snapshot() -> dict[str, Any]:
    """Return a plain nested copy for the diagnostics response and tests."""
    with _LOCK:
        data = dict(_COUNTERS)
    return {
        "sse": {
            "opened": data["sse.opened"],
            "closed": data["sse.closed"],
            "rejected": data["sse.rejected"],
            "slow_closed": data["sse.slow_closed"],
            "auth_revoked": data["sse.auth_revoked"],
            "max_age_closed": data["sse.max_age_closed"],
            "active_total": data["sse.active_total"],
        },
        "preview": {
            "frames": data["preview.frames"],
            "resets": data["preview.resets"],
            "dropped": data["preview.dropped"],
        },
        "notifier": {
            "published": data["notifier.published"],
            "failed": data["notifier.failed"],
        },
    }


def reset() -> None:
    """Clear every counter.  Tests use this; runtime never calls it."""
    with _LOCK:
        for key in _COUNTERS:
            _COUNTERS[key] = 0
