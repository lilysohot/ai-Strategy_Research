"""Machine-readable recovery scope for authoritative read failures.

Only typed authority errors are terminal. Unknown exceptions must not be
classified by matching their prose (which may contain source text).
"""

from __future__ import annotations

from typing import Any

from plugins.corpus.preparation import read_pg


def read_failure(exc: Exception) -> dict[str, Any]:
    """Describe whether the same read can succeed without external repair."""
    code, retryable, scope = "fetch_failed", True, "request"
    if isinstance(exc, read_pg.WithdrawnError):
        code, retryable, scope = "withdrawn", False, "document"
    elif isinstance(exc, read_pg.IntegrityError):
        code, retryable = "integrity", False
    elif isinstance(exc, read_pg.UnknownHandleError):
        code, retryable = "unknown_handle", False
    elif isinstance(exc, read_pg.LegacyHandleError):
        code, retryable = "archive_required", False
    return {"code": code, "retryable": retryable, "failure_scope": scope}
