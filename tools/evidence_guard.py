"""Refuse to overwrite signed or frozen evidence artifacts.

Wave 0 · P06. Before this module the signature guard lived only inside the sign-off and
merge scripts (evidence 43/45/46/47/48). Freeze and generation scripts, which can silently
overwrite an already-signed artifact, had no guard — D9 in
``evidence/44-replan-20261012``: "护栏只在单个脚本（部分闭合）".

Policy (issue-34 §8): 修订一律**新版本记录 + 旧哈希留存**；不就地修改既有产物.

Usage in a generation script::

    from tools.evidence_guard import write_once

    write_once(HERE / "preregistered-gate.json", payload, reason="issue-28 gate freeze")

``write_once`` refuses to touch a file that already carries a signature or a frozen status,
and by default refuses to overwrite anything at all.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

__all__ = [
    "SIGNATURE_MARKERS",
    "SIGNED_STATUSES",
    "SignedArtifactError",
    "artifact_state",
    "assert_writable",
    "write_once",
]

SIGNATURE_MARKERS: tuple[str, ...] = (
    "☑ 认可并签认",
    "☑ 认可本口径",
    "☑ 认可",
    "认可并签认",
    "复核人：",
    "human_signed",
    "signed_by",
)

SIGNED_STATUSES: frozenset[str] = frozenset(
    {
        "frozen",
        "frozen_signed",
        "frozen_before_execution",
        "signed",
        "human_signed",
        "human_signed_off",
        "countersigned",
        "proposed_pending_signoff",
    }
)

_COUNTERSIGNATURE_KEYS = (
    "countersignature",
    "signoff",
    "signature",
    "human_signature",
    "signed_by",
)

_TEXT_SUFFIXES = (".md", ".txt", ".markdown")


class SignedArtifactError(RuntimeError):
    """Raised when a write would overwrite a signed or frozen artifact."""


def artifact_state(path: Path) -> str:
    """Classify one path as ``missing``, ``plain``, or ``signed``.

    Structured formats are judged **structurally** — a JSON file merely *quoting* a signature
    marker (e.g. ``contract_binding.signed_by``) is not itself a signed artifact. Free-text
    review sheets are judged by marker, since they carry no schema.
    """
    if not path.exists():
        return "missing"
    if path.is_dir():
        return "plain"
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in _TEXT_SUFFIXES:
        return "signed" if any(marker in text for marker in SIGNATURE_MARKERS) else "plain"
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        return "plain"
    if not isinstance(payload, dict):
        return "plain"
    if str(payload.get("status") or "") in SIGNED_STATUSES:
        return "signed"
    return "signed" if any(payload.get(key) for key in _COUNTERSIGNATURE_KEYS) else "plain"


def assert_writable(path: Path, *, reason: str = "") -> None:
    """Raise ``SignedArtifactError`` when ``path`` must not be rewritten in place."""
    state = artifact_state(path)
    if state == "signed":
        suffix = f"（{reason}）" if reason else ""
        raise SignedArtifactError(
            f"拒绝写入：{path} 已含签认/冻结标记{suffix}；"
            "修订须以新版本记录 + 旧哈希留存（issue-34 §8）。"
        )


def write_once(
    path: Path,
    content: str | Any,
    *,
    reason: str = "",
    allow_overwrite: bool = False,
    ensure_ascii: bool = False,
) -> None:
    """Atomically write ``content``, refusing signed targets and (by default) existing files.

    ``content`` may be a ``str`` or any JSON-serialisable object.
    """
    assert_writable(path, reason=reason)
    if path.exists() and not allow_overwrite:
        raise SignedArtifactError(
            f"拒绝写入：{path} 已存在（write-once）。确需重跑请显式传入 allow_overwrite=True 或换新目录。"
        )
    text = (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=ensure_ascii, indent=2) + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
