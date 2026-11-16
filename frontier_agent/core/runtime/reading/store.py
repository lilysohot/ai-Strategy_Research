"""A file-backed home for installed checkpoints.

The framework deliberately ships no default store: where archives live is a
deployment decision, and the same reasoning that keeps ``EventStore`` a no-op here
applies. What it does ship is one correct implementation so callers do not each
invent their own atomicity.

Atomicity is not decoration. ``install_checkpoint`` treats a raising ``put`` as
"bodies must stay", so a partially written file must never look like a successful
put — hence write-temp-then-replace rather than "open and dump".
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from frontier_agent.core.runtime.reading.contract import (
    CheckpointBudget,
    CheckpointStatus,
    Coverage,
    Exclusion,
    Finding,
    FindingKind,
    ReadingCheckpoint,
    SourceRange,
)

__all__ = ["JsonCheckpointStore", "checkpoint_from_dict", "checkpoint_to_dict"]


def checkpoint_to_dict(checkpoint: ReadingCheckpoint) -> dict[str, Any]:
    """Serialise without losing the distinction between "absent" and "empty".

    ``StrEnum`` members are written as their string values on purpose: an archive
    that has to be readable by a later version should not depend on this version's
    enum class being importable.
    """
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "task_id": checkpoint.task_id,
        "question": checkpoint.question,
        "sources": [asdict(source) for source in checkpoint.sources],
        "findings": [
            {**asdict(finding), "kind": str(finding.kind)} for finding in checkpoint.findings
        ],
        "coverage": {
            "read_ranges": [asdict(rng) for rng in checkpoint.coverage.read_ranges],
            "unread_ranges": [asdict(rng) for rng in checkpoint.coverage.unread_ranges],
            "limitations": list(checkpoint.coverage.limitations),
            "complete": checkpoint.coverage.complete,
        },
        "excluded": [asdict(item) for item in checkpoint.excluded],
        "open_questions": list(checkpoint.open_questions),
        "budget": asdict(checkpoint.budget),
        "status": str(checkpoint.status),
        "supersedes": checkpoint.supersedes,
        "schema_version": checkpoint.schema_version,
    }


def _range_from(data: dict[str, Any]) -> SourceRange:
    return SourceRange(
        source_id=str(data.get("source_id") or ""),
        version=str(data.get("version") or ""),
        start=int(data.get("start") or 0),
        end=int(data.get("end") or 0),
        locator=str(data.get("locator") or ""),
    )


def checkpoint_from_dict(data: dict[str, Any]) -> ReadingCheckpoint:
    """Rebuild a checkpoint. Unknown kinds are kept as ``FACT`` rather than
    dropping the finding: losing a statement during a version skew is worse than
    mislabelling its shape."""

    def _kind(value: Any) -> FindingKind:
        try:
            return FindingKind(str(value))
        except ValueError:
            return FindingKind.FACT

    findings = tuple(
        Finding(
            finding_id=str(item.get("finding_id") or ""),
            kind=_kind(item.get("kind")),
            statement=str(item.get("statement") or ""),
            evidence_refs=tuple(str(ref) for ref in item.get("evidence_refs") or ()),
            source_id=str(item.get("source_id") or ""),
            value=str(item.get("value") or ""),
            unit=str(item.get("unit") or ""),
            period=str(item.get("period") or ""),
            condition=str(item.get("condition") or ""),
            contradicts=tuple(str(other) for other in item.get("contradicts") or ()),
        )
        for item in data.get("findings") or ()
        if isinstance(item, dict)
    )
    coverage_data = data.get("coverage") or {}
    status_value = str(data.get("status") or CheckpointStatus.DRAFT)
    try:
        status = CheckpointStatus(status_value)
    except ValueError:
        status = CheckpointStatus.REJECTED
    budget_data = data.get("budget") or {}
    return ReadingCheckpoint(
        checkpoint_id=str(data.get("checkpoint_id") or ""),
        task_id=str(data.get("task_id") or ""),
        question=str(data.get("question") or ""),
        findings=findings,
        sources=tuple(
            _range_from(source) for source in data.get("sources") or () if isinstance(source, dict)
        ),
        coverage=Coverage(
            read_ranges=tuple(
                _range_from(rng)
                for rng in coverage_data.get("read_ranges") or ()
                if isinstance(rng, dict)
            ),
            unread_ranges=tuple(
                _range_from(rng)
                for rng in coverage_data.get("unread_ranges") or ()
                if isinstance(rng, dict)
            ),
            limitations=tuple(str(item) for item in coverage_data.get("limitations") or ()),
            complete=bool(coverage_data.get("complete")),
        ),
        excluded=tuple(
            Exclusion(path=str(item.get("path") or ""), reason=str(item.get("reason") or ""))
            for item in data.get("excluded") or ()
            if isinstance(item, dict)
        ),
        open_questions=tuple(str(item) for item in data.get("open_questions") or ()),
        budget=CheckpointBudget(
            record_chars=int(budget_data.get("record_chars") or 0),
            record_limit=int(budget_data.get("record_limit") or 0),
            working_set_chars=int(budget_data.get("working_set_chars") or 0),
            working_set_limit=int(budget_data.get("working_set_limit") or 0),
        ),
        status=status,
        supersedes=str(data.get("supersedes") or ""),
        schema_version=int(data.get("schema_version") or 0),
    )


class JsonCheckpointStore:
    """One JSON file per checkpoint, written atomically.

    The id is sanitised into a filename rather than used verbatim: ids come from
    the caller and may contain ``:`` or ``/``.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def _path(self, checkpoint_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in checkpoint_id)
        if not safe:
            raise ValueError("checkpoint id has no filename-safe characters")
        return self.directory / f"{safe}.json"

    def put(self, checkpoint: ReadingCheckpoint) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(checkpoint.checkpoint_id)
        temp = path.with_suffix(".json.tmp")
        payload = json.dumps(
            checkpoint_to_dict(checkpoint),
            ensure_ascii=False,
            sort_keys=True,
        )
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, path)

    def get(self, checkpoint_id: str) -> ReadingCheckpoint | None:
        path = self._path(checkpoint_id)
        if not path.exists():
            return None
        return checkpoint_from_dict(json.loads(path.read_text(encoding="utf-8")))
