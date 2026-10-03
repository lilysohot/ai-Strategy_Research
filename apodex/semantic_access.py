"""Startup gate for the explicitly selected semantic-research experiment."""

from __future__ import annotations

import os
import re
from pathlib import Path


def require_readonly_semantic_store() -> None:
    """Refuse a visible writable store before exposing research tools or calling LLMs.

    File modes are insufficient when the researcher owns the files: it could
    chmod or replace them. Require a read-only filesystem mount, including any
    nested mounts. The launcher/operator must also exclude writable aliases of
    that store from the process namespace. Missing configuration/paths retain
    the existing query error and original-source fallback behavior.
    """
    raw = os.environ.get("CORPUS_STRUCTURED_ROOT", "").strip()
    if not raw:
        return
    message = (
        "tui-semantic requires a read-only publication-store mount. "
        "Prepare WAL sidecars on the writer side with prepare_readonly_access, "
        "then launch the research process with the store mounted read-only and "
        "no writable aliases. Native file modes alone are not a read-only boundary."
    )
    try:
        root = Path(raw).resolve()
        if not root.exists():
            return
        if not hasattr(os, "statvfs") or not os.statvfs(root).f_flag & os.ST_RDONLY:
            raise ValueError(message)
        # Linux bind mounts can hide a writable subtree under a read-only root.
        # Fail closed if the mount table cannot be inspected.
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            fields = line.split()
            mountpoint = Path(
                re.sub(
                    r"\\([0-7]{3})",
                    lambda m: chr(int(m[1], 8)),
                    fields[4],
                )
            )
            if mountpoint.is_relative_to(root) and "rw" in fields[5].split(","):
                raise ValueError(message)
    except (OSError, IndexError) as exc:
        raise ValueError(message) from exc
