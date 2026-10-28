"""Carry content-addressed corpus receipts between committed same-session runs."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def stage_corpus_receipts(
    *,
    target_run_dir: Path,
    source_runs: list[tuple[str, Path]],
    max_bytes: int = 16 * 1024 * 1024,
    max_files: int = 4096,
) -> None:
    """Copy bounded, hash-checked aliases; source identity/delivery is rechecked on use.

    The parent supplies only committed runs from this session. Receipts never
    grant the new worker filesystem access to a previous run or alter replay.
    """
    used = count = 0
    seen: set[tuple[str, str]] = set()
    for _run_id, source in reversed(source_runs):
        for directory, width in (("tool-refs", 32), ("search-refs", 64)):
            root = source / "run" / "corpus" / directory
            destination = target_run_dir / "run" / "corpus" / directory
            if not root.is_dir() or root.is_symlink():
                continue
            try:
                root.resolve().relative_to(source.resolve())
                destination.resolve().relative_to(target_run_dir.resolve())
                for path in sorted(root.iterdir()):
                    if count >= max_files or used >= max_bytes:
                        logger.warning("corpus receipt inheritance reached its size limit")
                        return
                    if (directory, path.name) in seen:
                        continue
                    if not re.fullmatch(rf"[0-9a-f]{{{width}}}\.json", path.name):
                        continue
                    if path.is_symlink() or not path.is_file():
                        continue
                    with path.open("rb") as stream:
                        raw = stream.read(1_000_001)
                    if len(raw) > 1_000_000 or used + len(raw) > max_bytes:
                        continue
                    if hashlib.sha256(raw).hexdigest()[:width] != path.stem:
                        continue
                    destination.mkdir(parents=True, exist_ok=True)
                    # Atomic copy; never follow an existing destination file symlink.
                    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=destination)
                    try:
                        with os.fdopen(fd, "wb") as stream:
                            stream.write(raw)
                        os.replace(temporary, destination / path.name)
                    finally:
                        Path(temporary).unlink(missing_ok=True)
                    seen.add((directory, path.name))
                    used += len(raw)
                    count += 1
            except (OSError, ValueError):
                logger.warning("could not inherit corpus receipts from %s", source)
