"""Explicit target binding for native retrieval deployments and historical reads."""

from __future__ import annotations

import os


def check_native_target(target: str | None) -> None:
    """Allow pilots, or a production database named by both independent settings.

    Callers still verify current_database() on the actual connection. Keeping the
    binding independent of the on/off switch lets issued citations survive rollback.
    """
    if target and target.startswith("vector_pilot_"):
        return
    if (
        not target
        or target in {"apodex", "template0", "template1"}
        or target != os.getenv("CORPUS_TARGET_DB", "").strip()
        or target != os.getenv("CORPUS_NATIVE_TARGET_DB", "").strip()
    ):
        raise ValueError("native_target_mismatch_not_explicitly_bound")
