"""Task-scoped, content-addressed file handoffs for agent-team members."""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from contextvars import Token
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plugins.tools._deliverable_policy import scratch_quota_bytes

HANDOFF_ROOT = "/outputs/scratch/handoffs"
MAX_REPORT_ATTACHMENTS = 8


@dataclass(frozen=True)
class HandoffScope:
    """Trusted physical roots and producer identity for one member task."""

    producer: str
    job_id: str
    workspace_root: Path
    outputs_root: Path


_HANDOFF_SCOPE: contextvars.ContextVar[HandoffScope | None] = contextvars.ContextVar(
    "agent_team_handoff_scope", default=None,
)
_PUBLISH_LOCK = threading.Lock()
_SAFE_COMPONENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_component(value: str, *, fallback: str) -> str:
    cleaned = _SAFE_COMPONENT_RE.sub("-", str(value or "").strip()).strip("-._")
    return (cleaned[:80] or fallback).lower()


def set_handoff_scope(
    *,
    producer: str,
    job_id: str,
    workspace_root: str | Path,
    outputs_root: str | Path,
) -> Token[HandoffScope | None]:
    """Bind the private producer workspace and shared output root."""
    return _HANDOFF_SCOPE.set(HandoffScope(
        producer=_safe_component(producer, fallback="member"),
        job_id=str(job_id or ""),
        workspace_root=Path(workspace_root).expanduser().resolve(),
        outputs_root=Path(outputs_root).expanduser().resolve(),
    ))


def reset_handoff_scope(token: Token[HandoffScope | None]) -> None:
    _HANDOFF_SCOPE.reset(token)


def get_handoff_scope() -> HandoffScope | None:
    return _HANDOFF_SCOPE.get()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _source_path(source_path: str, scope: HandoffScope) -> Path:
    raw = str(source_path or "").strip()
    if raw == "/workspace" or raw.startswith("/workspace/"):
        relative = raw.removeprefix("/workspace/")
        candidate = scope.workspace_root / relative
    else:
        candidate = Path(raw).expanduser()
    resolved = candidate.resolve(strict=True)
    if not _within(resolved, scope.workspace_root):
        raise ValueError("source_path must resolve to a file inside this member's /workspace")
    if not resolved.is_file():
        raise ValueError("source_path must name a regular file, not a directory")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scratch_usage(root: Path) -> int:
    scratch = root / "scratch"
    if not scratch.exists():
        return 0
    total = 0
    for path in scratch.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _trusted_handoff_root(scope: HandoffScope, *, create: bool) -> Path:
    """Resolve the handoff root without letting a scratch symlink redefine it."""
    outputs = scope.outputs_root.resolve(strict=True)
    scratch = scope.outputs_root / "scratch"
    handoffs = scratch / "handoffs"
    if create:
        scratch.mkdir(parents=True, exist_ok=True)
        if scratch.is_symlink() or handoffs.is_symlink():
            raise ValueError("the handoff store cannot be backed by a symlink")
        handoffs.mkdir(parents=True, exist_ok=True)
    if scratch.is_symlink() or handoffs.is_symlink():
        raise ValueError("the handoff store cannot be backed by a symlink")
    resolved = handoffs.resolve(strict=True)
    if not _within(resolved, outputs):
        raise ValueError("the handoff store escapes the task output root")
    return resolved


def _reject_symlinked_children(root: Path, target_parent: Path) -> None:
    """Reject producer/label directories redirected after root validation."""
    relative = target_parent.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("handoff producer and label directories cannot be symlinks")


def publish_file(source_path: str, label: str = "") -> dict[str, Any]:
    """Copy one private workspace file into the immutable shared handoff store."""
    scope = get_handoff_scope()
    if scope is None:
        raise RuntimeError("file handoff is available only inside an agent-team member task")
    source = _source_path(source_path, scope)
    digest = _sha256(source)
    size = source.stat().st_size
    producer = scope.producer
    logical_name = _safe_component(label, fallback=source.stem or "artifact")
    suffix = "".join(source.suffixes)[-32:]
    file_name = f"{digest[:16]}-{_safe_component(source.stem, fallback='artifact')}{suffix}"
    relative = Path("scratch") / "handoffs" / producer / logical_name / file_name
    destination = scope.outputs_root / relative
    canonical_ref = f"/outputs/{relative.as_posix()}"
    manifest_path = Path(f"{destination}.handoff.json")

    with _PUBLISH_LOCK:
        handoff_root = _trusted_handoff_root(scope, create=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = destination.parent.resolve(strict=True)
        if not _within(resolved_parent, handoff_root):
            raise ValueError("handoff destination escapes the controlled store")
        _reject_symlinked_children(handoff_root, destination.parent)
        if destination.is_symlink() or manifest_path.is_symlink():
            raise ValueError("handoff files and provenance cannot be symlinks")
        if destination.exists() and manifest_path.exists():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("sha256") == digest and _sha256(destination) == digest:
                return existing

        manifest: dict[str, Any] = {
            "ok": True,
            "schema_version": 1,
            "ref": canonical_ref,
            "sha256": digest,
            "size_bytes": size,
            "version": digest[:16],
            "producer": producer,
            "job_id": scope.job_id,
            "label": logical_name,
            "source_name": source.name,
            "created_at": datetime.now(UTC).isoformat(),
        }
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, indent=2,
        ).encode("utf-8")
        if _scratch_usage(scope.outputs_root) + size + len(manifest_bytes) > scratch_quota_bytes():
            raise ValueError(
                "publishing this handoff would exceed the /outputs/scratch quota"
            )

        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with source.open("rb") as src:
                shutil.copyfileobj(src, tmp)
        os.replace(tmp_path, destination)
        destination.chmod(0o444)

        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, delete=False,
        ) as tmp_manifest:
            tmp_manifest.write(manifest_bytes)
            tmp_manifest_path = Path(tmp_manifest.name)
        os.replace(tmp_manifest_path, manifest_path)
        manifest_path.chmod(0o444)
        return manifest


def _handoff_path(ref: str, scope: HandoffScope) -> tuple[Path, Path]:
    raw = str(ref or "").strip()
    prefix = f"{HANDOFF_ROOT}/"
    if not raw.startswith(prefix):
        raise ValueError(f"{raw!r} is not a controlled handoff reference")
    relative = Path(raw.removeprefix("/outputs/"))
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"{raw!r} is not a normalized handoff reference")
    target = (scope.outputs_root / relative).resolve(strict=True)
    handoff_root = _trusted_handoff_root(scope, create=False)
    if not _within(target, handoff_root) or not target.is_file():
        raise ValueError(f"{raw!r} does not resolve inside the handoff store")
    return target, Path(f"{target}.handoff.json")


def validate_handoff_refs(
    refs: list[str] | None, *, outputs_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Validate referenced files and their provenance manifests by digest."""
    if not refs:
        return []
    if len(refs) > MAX_REPORT_ATTACHMENTS:
        raise ValueError(
            f"at most {MAX_REPORT_ATTACHMENTS} handoff attachments may be submitted"
        )
    scope = get_handoff_scope()
    if outputs_root is not None:
        root = outputs_root.resolve()
        scope = HandoffScope("coordinator", "", root, root)
    if scope is None:
        raise RuntimeError("file handoff is available only inside an agent-team member task")
    manifests: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        target, manifest_path = _handoff_path(ref, scope)
        if ref in seen:
            continue
        seen.add(ref)
        if not manifest_path.is_file():
            raise ValueError(f"handoff provenance is missing for {ref!r}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("ref") != ref:
            raise ValueError(f"handoff provenance does not match {ref!r}")
        digest = _sha256(target)
        if manifest.get("sha256") != digest:
            raise ValueError(f"handoff digest verification failed for {ref!r}")
        manifests.append(manifest)
    return manifests


__all__ = [
    "HANDOFF_ROOT",
    "MAX_REPORT_ATTACHMENTS",
    "get_handoff_scope",
    "publish_file",
    "reset_handoff_scope",
    "set_handoff_scope",
    "validate_handoff_refs",
]
