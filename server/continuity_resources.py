"""Stage auditable resources from committed runs into a later run's /inputs.

Conversation state carries prose.  This module carries bytes without granting a
new worker access to an old run directory: same-session run ids are selected by
the parent store, copied by digest, and exposed read-only with their provenance.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str, fallback: str = "resource") -> str:
    return (_SAFE_NAME.sub("-", value).strip("-._")[:120] or fallback).lower()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _verification_for_ref(summary: dict[str, Any], ref: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    contract = summary.get("report_contract")
    source_checks = contract.get("verification_checks", []) if isinstance(contract, dict) else []
    for raw in source_checks:
        if not isinstance(raw, dict):
            continue
        sources = [raw.get("subject"), *(raw.get("evidence") or [])]
        if not any(isinstance(source, dict) and source.get("ref") == ref for source in sources):
            continue
        checks.append(
            {
                "check_id": str(raw.get("check_id") or ""),
                "criterion": str(raw.get("criterion") or "")[:2000],
                "binding_id": str(raw.get("binding_id") or ""),
                "verdict": str(raw.get("verdict") or "unchecked"),
                "job_id": str(raw.get("verdict_job_id") or raw.get("job_id") or ""),
            }
        )
    if not checks:
        status = "not_assessed"
    elif any(check["verdict"] == "fail" for check in checks):
        status = "failed_for_declared_checks"
    elif all(check["verdict"] == "pass" for check in checks):
        status = "passed_for_declared_checks"
    else:
        status = "partial"
    return {"verification_status": status, "verification_checks": checks}


def _copy_one(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        with source.open("rb") as stream:
            shutil.copyfileobj(stream, handle)
        handle.flush()
        with contextlib.suppress(OSError):
            os.fsync(handle.fileno())
    os.replace(temporary, destination)
    destination.chmod(0o444)


def stage_continuity_resources(
    *,
    target_run_dir: Path,
    source_runs: list[tuple[str, Path]],
    max_files: int = 40,
    max_bytes: int = 100 * 1024 * 1024,
) -> dict[str, Any]:
    """Copy eligible resources and return their immutable provenance manifest."""
    target_inputs = target_run_dir / "inputs"
    target_inputs.mkdir(parents=True, exist_ok=True)
    history_root = target_inputs / "history"
    if history_root.is_symlink() or (history_root.exists() and not history_root.is_dir()):
        history_root.unlink()
    elif history_root.exists():
        shutil.rmtree(history_root)
    history_root.mkdir(parents=True, exist_ok=True)
    resources: list[dict[str, Any]] = []
    limitations: list[dict[str, str]] = []
    used = 0

    def add(
        *,
        source: Path,
        source_run_id: str,
        kind: str,
        source_ref: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        nonlocal used
        if len(resources) >= max_files:
            limitations.append({"source_run_id": source_run_id, "reason": "file_limit"})
            return
        try:
            if source.is_symlink() or not source.is_file():
                raise OSError("not a regular non-symlink file")
            size = source.stat().st_size
            digest = _sha256(source)
        except OSError as exc:
            limitations.append({"source_run_id": source_run_id, "reason": str(exc)[:240]})
            return
        if used + size > max_bytes:
            limitations.append({"source_run_id": source_run_id, "reason": "byte_limit"})
            return
        name = f"{digest[:16]}-{_safe_name(source.name)}"
        relative = Path("history") / _safe_name(source_run_id, "run") / kind / name
        destination = target_inputs / relative
        try:
            _copy_one(source, destination)
        except OSError as exc:
            limitations.append(
                {
                    "source_run_id": source_run_id,
                    "reason": f"copy_failed:{type(exc).__name__}",
                }
            )
            return
        used += size
        item: dict[str, Any] = {
            "kind": kind,
            "path": f"/inputs/{relative.as_posix()}",
            "source_run_id": source_run_id,
            "source_ref": source_ref,
            "sha256": digest,
            "size_bytes": size,
            "verification_status": "not_assessed",
            "verification_checks": [],
        }
        item.update(metadata or {})
        resources.append(item)

    # Newest committed runs win the bounded inventory while preserving stable
    # order within each run.
    for source_run_id, source_root in reversed(source_runs):
        summary = _read_json(source_root / "summary.json")
        inputs = source_root / "inputs"
        if inputs.is_dir() and not inputs.is_symlink():
            try:
                input_entries = sorted(inputs.iterdir(), key=lambda item: item.name)
            except OSError as exc:
                limitations.append(
                    {
                        "source_run_id": source_run_id,
                        "reason": f"inputs_unavailable:{type(exc).__name__}",
                    }
                )
                input_entries = []
            for source in input_entries:
                if source.name == "history":
                    continue
                add(
                    source=source,
                    source_run_id=source_run_id,
                    kind="upload",
                    source_ref=f"run:{source_run_id}/inputs/{source.name}",
                )
        handoff_root = source_root / "ws" / "outputs" / "scratch" / "handoffs"
        if not handoff_root.is_dir() or handoff_root.is_symlink():
            continue
        for directory, dirs, files in os.walk(handoff_root, followlinks=False):
            dirs[:] = sorted(name for name in dirs if not (Path(directory) / name).is_symlink())
            for name in sorted(files):
                if not name.endswith(".handoff.json"):
                    continue
                manifest = _read_json(Path(directory) / name)
                ref = str(manifest.get("ref") or "")
                prefix = "/outputs/scratch/handoffs/"
                if not ref.startswith(prefix):
                    limitations.append(
                        {"source_run_id": source_run_id, "reason": "invalid_handoff_ref"}
                    )
                    continue
                candidate = source_root / "ws" / "outputs" / ref.removeprefix("/outputs/")
                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(handoff_root.resolve(strict=True))
                    expected = str(manifest.get("sha256") or "")
                    if candidate.is_symlink() or not expected or _sha256(resolved) != expected:
                        raise ValueError("handoff digest mismatch")
                except (OSError, ValueError):
                    limitations.append(
                        {"source_run_id": source_run_id, "reason": "invalid_handoff_bytes"}
                    )
                    continue
                add(
                    source=resolved,
                    source_run_id=source_run_id,
                    kind="handoff",
                    source_ref=ref,
                    metadata={
                        "producer": str(manifest.get("producer") or ""),
                        "job_id": str(manifest.get("job_id") or ""),
                        **_verification_for_ref(summary, ref),
                    },
                )
    manifest = {
        "schema": "continuity-resources/1",
        "resources": resources,
        "limitations": limitations,
        "total_bytes": used,
    }
    destination = target_run_dir / "prior_resources.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, destination)
    return manifest


def continuity_resource_prompt(manifest: dict[str, Any]) -> str:
    """Render paths and provenance only; file content remains tool-on-demand."""
    resources = manifest.get("resources") or []
    limitations = [
        {
            "source_run_id": str(item.get("source_run_id") or ""),
            "reason": str(item.get("reason") or "")[:240],
        }
        for item in manifest.get("limitations") or []
        if isinstance(item, dict)
    ][:40]
    if not resources and not limitations:
        return ""
    inventory = []
    for item in resources:
        if not isinstance(item, dict):
            continue
        projected = {
            key: item.get(key)
            for key in (
                "kind",
                "path",
                "source_run_id",
                "source_ref",
                "sha256",
                "verification_status",
            )
        }
        projected["verification_checks"] = [
            {
                "check_id": check.get("check_id"),
                "criterion": str(check.get("criterion") or "")[:240],
                "binding_id": check.get("binding_id"),
                "verdict": check.get("verdict"),
            }
            for check in item.get("verification_checks") or []
            if isinstance(check, dict)
        ]
        inventory.append(projected)
    return (
        "# Inherited run resources\n"
        "These read-only files come from committed earlier runs in this same conversation. "
        "Read them with read_file only when relevant. Preserve source_run_id and sha256 when "
        "citing them. A prior verdict is scoped only to its listed check/version; not_assessed "
        "is not verified. Do not claim the current report or transformed content was verified "
        "from a historical verdict alone.\n"
        + json.dumps(
            {"resources": inventory, "limitations": limitations},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
