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
import re
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

# A blank review *template* also contains the words "复核人：" and an unchecked "☐ 认可并签认",
# so a plain substring match misclassifies every empty template as signed (found 2026-10-12
# while regenerating the v4.2 draft). A text file counts as signed only when a signature was
# actually filled in: a reviewer name, a checked box, or an explicit x-mark on the conclusion line.
_REVIEWER_LINE = re.compile(r"复核人：([^\n]*)")
_DATE_LABEL = re.compile(r"日期[:：]?.*$", re.DOTALL)


def _reviewer_name_filled(text: str) -> bool:
    """True when at least one 复核人 line carries a name rather than only a date label."""
    for tail in _REVIEWER_LINE.findall(text):
        remainder = _DATE_LABEL.sub("", tail.strip()).strip(" ：:\u3000")
        if remainder:
            return True
    return False


_TEXT_SIGNATURE_PATTERNS = (
    re.compile(r"☑"),
    re.compile(r"(?m)^\s*-\s*结论：\s*x\s"),
)


class SignedArtifactError(RuntimeError):
    """Raised when a write would overwrite a signed or frozen artifact."""


def _signoff_block_filled(payload: dict[str, Any]) -> bool:
    """True only when a ``signoff`` block actually carries a signature.

    A draft may legitimately contain an empty ``signoff`` placeholder; treating its mere
    presence as a signature misclassified the v4.2 draft as signed (found 2026-10-12).
    """
    signoff = payload.get("signoff")
    if not isinstance(signoff, dict):
        return bool(signoff)
    return bool(str(signoff.get("signed_by") or "").strip()) or bool(signoff.get("instrument"))


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
        if _reviewer_name_filled(text):
            return "signed"
        return (
            "signed"
            if any(pattern.search(text) for pattern in _TEXT_SIGNATURE_PATTERNS)
            else "plain"
        )
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        return "plain"
    if not isinstance(payload, dict):
        return "plain"
    if str(payload.get("status") or "") in SIGNED_STATUSES:
        return "signed"
    for key in _COUNTERSIGNATURE_KEYS:
        if key == "signoff":
            if _signoff_block_filled(payload):
                return "signed"
        elif payload.get(key):
            return "signed"
    return "plain"


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
