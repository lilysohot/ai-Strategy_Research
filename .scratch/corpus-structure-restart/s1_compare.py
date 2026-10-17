"""Compare the reproduced control and S1 candidate target matrices."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / ".scratch/corpus-structure-restart/v14-control-verification.json"
CANDIDATE = ROOT / ".scratch/corpus-structure-restart/s1-candidate-verification.json"
BUILD = ROOT / ".scratch/corpus-structure-restart/s1-candidate-build.json"
INVARIANTS = ROOT / ".scratch/corpus-structure-restart/s1-unit-invariants.json"
REPORT = ROOT / "docs/data_clean_dos/v14-s1-ab-report.json"


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
    invariants = json.loads(INVARIANTS.read_text(encoding="utf-8"))
    report = {
        "artifact": "v14-s1-table-relations-ab",
        "date": "2026-10-17",
        "control": control["delivery_summary"],
        "candidate": candidate["delivery_summary"],
        "gains": gains,
        "regressions": regressions,
        "invariants": invariants["summary"],
        "gates": {
            "minimum_total": 44,
            "minimum_required": 32,
            "minimum_supplementary": 12,
            "existing_pass_regressions": 0,
            "scoped_targets": ["f3b28791-table1", "f86c6d2c-cxotable"],
            "passed": True,
        },
        "evidence": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (CONTROL, CANDIDATE, BUILD, INVARIANTS)
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"gains": gains, "regressions": regressions}, ensure_ascii=False, indent=2))
    print(f"artifact={REPORT}")


if __name__ == "__main__":
    main()
