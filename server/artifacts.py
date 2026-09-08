"""Artifact discovery: scan a run's deliverables into the artifacts table (T2.9).

Per-run layout (tech-stack.md §5.1-6)::

    server/runs/<run_id>/
      ws/                FRONTIER_AGENT_WORKSPACE_DIR + CODING_WORKSPACE_ROOT
        outputs/         FRONTIER_AGENT_OUTPUTS_DIR  ← the only deliverable root

``outputs`` **must** be nested inside ``workspace``: ``CODING_WORKSPACE_ROOT``
authorises exactly one write root, so a sibling ``outputs/`` would be rejected by
path authorisation. That layout is why scanning is well-defined — every file the
agent was allowed to deliver lives under one directory.

Responsibilities:

  * :func:`scan_outputs` — walk the outputs dir when a run reaches a terminal
    state and produce ``{rel_path, size, sha256}`` rows for the artifacts table.
  * :func:`resolve_artifact_path` — the single containment check used by the
    download endpoint. A caller-supplied ``rel_path`` is resolved against the
    run's outputs dir and rejected if it escapes it (``../``, absolute paths,
    symlinks pointing outside).

Scanning is deliberately bounded: a run that somehow produced a huge tree must
not stall the orchestrator or bloat the database (see :data:`_MAX_FILES` /
:data:`_MAX_FILE_BYTES`).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

from server.config import run_dir_for

# Outputs sit inside the workspace root (see module docstring); this is the
# single place that fact is encoded, so a layout change touches one function.
_OUTPUTS_REL = Path("ws") / "outputs"

# Bounds: a run should deliver a handful of files, not a filesystem. Exceeding
# these is not an error — we simply stop recording, so a pathological run cannot
# stall the orchestrator or blow up the artifacts table.
_MAX_FILES = 500
_MAX_FILE_BYTES = 256 * 1024 * 1024  # skip hashing anything larger


def outputs_dir_for(run_id: str) -> Path:
    """The per-run deliverable root (``<run_dir>/ws/outputs``)."""
    return run_dir_for(run_id) / _OUTPUTS_REL


def _sha256_of(path: Path) -> str | None:
    """Stream a file through sha256; ``None`` if unreadable or too large."""
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
    except OSError:
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _iter_files(root: Path) -> Iterator[Path]:
    """Yield regular files under ``root``, skipping symlinked dirs and stray links.

    ``os.walk(followlinks=False)`` keeps a malicious or accidental symlink loop
    from sending the scan outside the outputs tree.
    """
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Prune symlinked directories so we never walk outside the root.
        dirnames[:] = [
            d for d in dirnames if not (Path(dirpath) / d).is_symlink()
        ]
        for name in filenames:
            candidate = Path(dirpath) / name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            yield candidate


def scan_outputs(run_id: str) -> list[dict]:
    """Return ``[{rel_path, size, sha256}]`` for every file in the outputs dir.

    ``rel_path`` is posix-style and relative to the outputs root — that is the
    artifacts table's key and what the download endpoint accepts. Files we cannot
    stat or hash are still recorded (with size/sha256 ``None``) so the UI can show
    that something was produced; only the count bound stops the scan early.
    """
    root = outputs_dir_for(run_id)
    out: list[dict] = []
    for path in _iter_files(root):
        if len(out) >= _MAX_FILES:
            break
        rel = path.relative_to(root).as_posix()
        try:
            size: int | None = path.stat().st_size
        except OSError:
            size = None
        out.append({
            "rel_path": rel,
            "size": size,
            "sha256": _sha256_of(path),
        })
    return out


def resolve_artifact_path(run_id: str, rel_path: str) -> Path | None:
    """Resolve a caller-supplied ``rel_path`` inside the run's outputs dir.

    Returns ``None`` when the path escapes the deliverable root — absolute paths,
    ``..`` traversal, and symlinks that resolve outside are all rejected. This is
    the *only* way the download endpoint turns a request parameter into a
    filesystem path, so containment is enforced here in one place.
    """
    if not rel_path or rel_path.startswith("/") or "\x00" in rel_path:
        return None
    # Reject Windows-style absolute paths too (``C:\...``) — we only ever accept
    # a relative, posix-shaped path.
    if len(rel_path) > 1 and rel_path[1] == ":":
        return None
    root = outputs_dir_for(run_id)
    try:
        candidate = (root / rel_path).resolve()
        root_resolved = root.resolve()
    except (OSError, ValueError):
        return None
    # is_relative_to is the containment test: equal to the root itself is also
    # rejected (that would be a directory, not a file).
    if candidate == root_resolved or not candidate.is_relative_to(root_resolved):
        return None
    if not candidate.is_file():
        return None
    return candidate


__all__ = ["outputs_dir_for", "resolve_artifact_path", "scan_outputs"]
