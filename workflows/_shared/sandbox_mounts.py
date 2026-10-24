"""Shared parsing for workflow sandbox paths supplied through metadata."""

from __future__ import annotations

import logging
import posixpath
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SandboxBind = tuple[str, str, bool]


def workspace_root_override(metadata: Mapping[str, Any]) -> Path | None:
    """Return the explicit per-Run workspace path, if one was supplied."""
    raw = str(metadata.get("_sandbox_workspace_root") or "").strip()
    return Path(raw).expanduser() if raw else None


def resolve_sandbox_mount_metadata(
    metadata: Mapping[str, Any],
    worktree_root: Path,
) -> tuple[tuple[SandboxBind, ...], Path]:
    """Resolve declared read mounts and the workflow's physical outputs path.

    Metadata may originate from the Web worker or the benchmark adapter. Only
    canonical destinations within ``/inputs`` are accepted; lexical prefix
    checks alone would also accept ``/inputs_evil`` and ``/inputs/../etc``.
    """
    outputs_raw = str(metadata.get("_sandbox_outputs_dir") or "").strip()
    outputs_dir = (
        Path(outputs_raw).expanduser()
        if outputs_raw
        else worktree_root.parent / "outputs"
    )
    dataset_raw = str(metadata.get("_dataset_root") or "").strip()
    dataset_root = Path(dataset_raw).expanduser() if dataset_raw else None

    inputs: list[SandboxBind] = []
    for mount in metadata.get("_sandbox_mounts") or []:
        if not isinstance(mount, Mapping):
            logger.warning("sandbox mount entry is not an object, skipped: %r", mount)
            continue
        source_raw = str(mount.get("src") or "").strip()
        destination_raw = str(mount.get("dst") or "").strip()
        if not source_raw or not destination_raw:
            continue
        destination = posixpath.normpath(destination_raw)
        if destination != "/inputs" and not destination.startswith("/inputs/"):
            logger.warning(
                "sandbox mount dst not under /inputs, skipped: %s",
                destination_raw,
            )
            continue

        source = Path(source_raw).expanduser()
        if not source.is_absolute() and dataset_root is not None:
            source = dataset_root / source
        if str(mount.get("mode", "ro")).lower() == "rw":
            logger.warning(
                "sandbox input mount requested rw mode; forcing read-only: %s",
                destination,
            )
        inputs.append((str(source.resolve()), destination, True))

    return tuple(inputs), outputs_dir


__all__ = [
    "SandboxBind",
    "resolve_sandbox_mount_metadata",
    "workspace_root_override",
]
