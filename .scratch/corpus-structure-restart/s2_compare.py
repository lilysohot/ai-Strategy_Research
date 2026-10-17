"""Compare the frozen S1 and S2 51-target delivery matrices."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / ".scratch/corpus-structure-restart"
CONTROL = HERE / "s1-candidate-verification.json"
CANDIDATE = HERE / "s2-candidate-verification.json"
BUILD = HERE / "s2-candidate-build.json"
INVARIANTS = HERE / "s2-unit-invariants.json"
REPRO = HERE / "s2-quote-repro.json"
REPORT = ROOT / "docs/data_clean_dos/v14-s2-ab-report.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    before = {row["target_id"]: row for row in control["target_results"]}
    after = {row["target_id"]: row for row in candidate["target_results"]}
    changed = []
    for target_id in sorted(before):
        old = before[target_id]
        new = after[target_id]
        if old["all_pass"] != new["all_pass"] or old["first_fail"] != new["first_fail"]:
            changed.append(
                {
                    "target_id": target_id,
                    "role": new["role"],
                    "before": {"pass": old["all_pass"], "first_fail": old["first_fail"]},
                    "after": {"pass": new["all_pass"], "first_fail": new["first_fail"]},
                    "quote": [old["quote_delivered"], new["quote_delivered"]],
                    "dependencies": [old["dependencies"], new["dependencies"]],
                }
            )
    regressions = [row for row in changed if row["before"]["pass"] and not row["after"]["pass"]]
    gains = [row for row in changed if not row["before"]["pass"] and row["after"]["pass"]]
    remaining = [
        {
            "target_id": row["target_id"],
            "role": row["role"],
            "first_fail": row["first_fail"],
        }
        for row in candidate["target_results"]
        if not row["all_pass"]
    ]
    invariants = json.loads(INVARIANTS.read_text(encoding="utf-8"))
    summary = candidate["delivery_summary"]
    gates = {
        "minimum_total": 49,
        "minimum_required": 35,
        "minimum_supplementary": 14,
        "existing_pass_regressions": 0,
        "scoped_targets": [
            "c1ddcd8a-summarytable",
            "b7e932c8-index",
            "b7e932c8-industry",
        ],
    }
    gates["passed"] = (
        summary["passed"] >= gates["minimum_total"]
        and summary["by_role"]["required"]["passed"] >= gates["minimum_required"]
        and summary["by_role"]["supplementary"]["passed"]
        >= gates["minimum_supplementary"]
        and len(regressions) == gates["existing_pass_regressions"]
        and {row["target_id"] for row in gains} == set(gates["scoped_targets"])
    )
    report = {
        "artifact": "v14-s2-quote-delivery-ab",
        "date": "2026-10-17",
        "control": control["delivery_summary"],
        "candidate": summary,
        "gains": gains,
        "regressions": regressions,
        "remaining_failures": remaining,
        "invariants": invariants["summary"],
        "gates": gates,
        "evidence": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (CONTROL, CANDIDATE, BUILD, INVARIANTS, REPRO)
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if gates["passed"] else 1)


if __name__ == "__main__":
    main()
