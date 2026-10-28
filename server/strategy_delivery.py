"""Persist business validation and restrict delivery of unvalidated strategy drafts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

RECEIPT_NAME = "investment-strategy-verification.json"


def persist_strategy_verification(run_root: Path) -> None:
    from plugins.tools.investment_strategy import (
        capital_analysis_text,
        published_research_text,
        validation_snapshot,
    )

    result = validation_snapshot()
    if result is None:
        return
    # None leaves ordinary artifact discovery unchanged. An explicit allowlist
    # prevents model-written drafts from being presented as validated reports.
    result["allowed_artifacts"] = None if result.get("recommendation_allowed") else {}
    receipt = run_root / RECEIPT_NAME
    _write_json(receipt, result)
    if result.get("passed") and result.get("delivery_mode") == "capital_analysis":
        output_root = run_root / "ws" / "outputs"
        if output_root.is_symlink() or output_root.parent.is_symlink():
            return
        output_root.mkdir(parents=True, exist_ok=True)
        deliverables = {"investment-analysis.md": capital_analysis_text(result)}
        research = published_research_text()
        if research:
            deliverables["research-analysis.md"] = research
        allowed = {}
        for name, text in deliverables.items():
            content = text.encode("utf-8")
            temporary = output_root / ("." + name + ".tmp")
            # Exclusive creation avoids following a model-created temporary symlink.
            with temporary.open("xb") as handle:
                handle.write(content)
            os.replace(temporary, output_root / name)
            allowed[name] = hashlib.sha256(content).hexdigest()
        result["allowed_artifacts"] = allowed
        _write_json(receipt, result)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def artifact_allowed(run_root: Path, rel_path: str, digest: str | None) -> bool:
    receipt = run_root / RECEIPT_NAME
    if not receipt.exists():
        return True  # Historical/non-business Runs retain the existing behavior.
    try:
        result = json.loads(receipt.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            return False
        allowed = result.get("allowed_artifacts", {})
        if allowed is None:
            return result.get("recommendation_allowed") is True
        return isinstance(allowed, dict) and digest is not None and allowed.get(rel_path) == digest
    except (OSError, ValueError):
        return False
