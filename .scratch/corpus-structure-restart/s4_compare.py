"""Compare the frozen S3 and S4 51-target delivery matrices."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / ".scratch/corpus-structure-restart"
CONTROL = HERE / "s3-candidate-verification.json"
CANDIDATE = HERE / "s4-candidate-verification.json"
BUILD = HERE / "s2-candidate-build.json"
INVARIANTS = HERE / "s2-unit-invariants.json"
PROBE = HERE / "s4-source-probe.json"
REPRO = HERE / "s4-source-repro.json"
REPORT = ROOT / "docs/data_clean_dos/v14-s4-ab-report.json"
SCOPED_TARGET = "f7f65d7e-risk"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state(row: dict[str, object]) -> dict[str, object]:
    return {
        "pass": row["all_pass"],
        "first_fail": row["first_fail"],
        "search_hits": row["search_hits"],
        "source_offered": row["source_offered"],
        "plans": row["plans"],
        "pages": row["pages"],
        "fetch_complete": row["fetch_complete"],
        "quote_delivered": row["quote_delivered"],
    }


def main() -> None:
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    before = {row["target_id"]: row for row in control["target_results"]}
    after = {row["target_id"]: row for row in candidate["target_results"]}
    changed = [
        {
            "target_id": target_id,
            "role": after[target_id]["role"],
            "before": _state(before[target_id]),
            "after": _state(after[target_id]),
        }
        for target_id in sorted(before)
        if before[target_id]["all_pass"] != after[target_id]["all_pass"]
        or before[target_id]["first_fail"] != after[target_id]["first_fail"]
    ]
    gains = [row for row in changed if not row["before"]["pass"] and row["after"]["pass"]]
    regressions = [row for row in changed if row["before"]["pass"] and not row["after"]["pass"]]
    remaining = [
        {
            "target_id": row["target_id"],
            "role": row["role"],
            "first_fail": row["first_fail"],
        }
        for row in candidate["target_results"]
        if not row["all_pass"]
    ]
    summary = candidate["delivery_summary"]
    gates = {
        "total": 51,
        "required": 36,
        "supplementary": 15,
        "existing_pass_regressions": 0,
        "scoped_targets": [SCOPED_TARGET],
    }
    gates["passed"] = (
        summary["passed"] == gates["total"]
        and summary["by_role"]["required"]["passed"] == gates["required"]
        and summary["by_role"]["supplementary"]["passed"] == gates["supplementary"]
        and len(regressions) == gates["existing_pass_regressions"]
        and {row["target_id"] for row in gains} == set(gates["scoped_targets"])
    )
    invariant_summary = json.loads(INVARIANTS.read_text(encoding="utf-8"))["summary"]
    report = {
        "artifact": "v14-s4-source-coverage-ab",
        "date": "2026-10-17",
        "scope": {
            "change": "source-level candidate-query lexeme coverage before max chunk score",
            "database": "v14_s2_quote_corpus",
            "database_rebuilt": False,
        },
        "control": control["delivery_summary"],
        "candidate": summary,
        "gains": gains,
        "regressions": regressions,
        "remaining_failures": remaining,
        "invariants": invariant_summary,
        "gates": gates,
        "evidence": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (CONTROL, CANDIDATE, BUILD, INVARIANTS, PROBE, REPRO)
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if gates["passed"] else 1)


if __name__ == "__main__":
    main()
