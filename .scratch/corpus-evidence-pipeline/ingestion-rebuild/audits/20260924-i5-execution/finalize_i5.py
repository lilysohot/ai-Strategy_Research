"""Bind I5 replay evidence, code, scripts, guards, and documents into one immutable record."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
REPLAYS = {
    "s1": "i51-s1-rerun-report.json",
    "s2": "i51-s2-srcchange-report.json",
    "s3": "i51-s3-newrule-report.json",
    "s4": "i51-s4-idxreb-report.json",
}
BOUND_FILES = [
    "plugins/corpus/preparation/readers/__init__.py",
    "plugins/corpus/service.py",
    "scripts/corpus_evidence_pilot.py",
    "scripts/corpus_holdout_eval.py",
    "tests/test_corpus_preparation_release_gate.py",
    "tests/test_corpus_consumers_pg.py",
    "tests/test_corpus_ingest_retired.py",
    "docs/corpus-ingestion-operations.md",
    "docs/corpus-ingestion-retirement-matrix.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i5-scenarios.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260924-i51-scenarios/i51_common.py",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260924-i5-execution/replay_i51_scenarios.py",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    target = OUT / "i5-final-binding.json"
    if target.exists():
        raise SystemExit(f"write-once conflict: {target}")
    scenarios: dict[str, object] = {}
    all_green = True
    for name, report_name in REPLAYS.items():
        directory = OUT / f"replay-{name}-post-f1"
        report_path = directory / report_name
        wrapper_path = directory / "wrapper-results.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        status = bool(
            report.get("gate_passed")
            and wrapper.get("execution_exit_code") == 0
            and wrapper.get("sandbox_restored_exact_table_contents")
            and wrapper.get("production_readonly_pre_post_equal")
            and wrapper.get("production_snapshot_readonly")
        )
        if name == "s1":
            summary = report.get("summary") or {}
            status = bool(
                status
                and len(summary.get("replay_build_id_stable") or []) == 8
                and not (summary.get("replay_build_id_churned") or [])
            )
        scenarios[name] = {
            "report": str(report_path.relative_to(ROOT)),
            "report_sha256": sha256(report_path),
            "wrapper": str(wrapper_path.relative_to(ROOT)),
            "wrapper_sha256": sha256(wrapper_path),
            "passed": status,
        }
        all_green = all_green and status
    payload = {
        "artifact": "i5-final-binding",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "I5-1 four-scenario replay, I5-2 operations, I5-3 retirement verification",
        "scenarios": scenarios,
        "bound_files": {name: sha256(ROOT / name) for name in BOUND_FILES},
        "acceptance": {
            "four_scenarios_passed": all_green,
            "s1_checkpoint_replay_8_of_8_stable": bool(scenarios["s1"]["passed"]),
            "each_sandbox_restored": all(
                bool(
                    json.loads(
                        (OUT / f"replay-{name}-post-f1/wrapper-results.json").read_text(
                            encoding="utf-8"
                        )
                    )["sandbox_restored_exact_table_contents"]
                )
                for name in REPLAYS
            ),
            "each_production_snapshot_explicitly_readonly": all(
                bool(
                    json.loads(
                        (OUT / f"replay-{name}-post-f1/wrapper-results.json").read_text(
                            encoding="utf-8"
                        )
                    )["production_snapshot_readonly"]
                )
                for name in REPLAYS
            ),
        },
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["acceptance"], ensure_ascii=False, indent=2))
    return 0 if all(payload["acceptance"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
