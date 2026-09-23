"""Append the passing M6 product revision without rewriting historical snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
INDEX = FREEZES / "freeze-manifest.json"
SNAPSHOT = FREEZES / "i0c-r5e.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(paths: list[str]) -> dict[str, str]:
    return {path: digest(ROOT / path) for path in sorted(paths)}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = index["snapshots"]
    if any(row["snapshot_id"] == "i0c-r5e" for row in rows) or SNAPSHOT.exists():
        raise RuntimeError("i0c-r5e already exists; append a new revision instead")
    if not rows or rows[-1]["snapshot_id"] != "i0c-r5d":
        raise RuntimeError("i0c-r5e must append directly after i0c-r5d")
    for row in rows:
        path = FREEZES / row["file"]
        if digest(path) != row["sha256"]:
            raise RuntimeError(f"historical snapshot drift: {row['snapshot_id']}")

    implementation = [
        "plugins/corpus/preparation/negative_query.py",
        "plugins/corpus/preparation/search_pg.py",
        "plugins/corpus/preparation/selection.py",
        "plugins/corpus/service.py",
        "plugins/tools/corpus_fetch.py",
        "plugins/tools/corpus_search.py",
        "tools/corpus_product_observations.py",
    ]
    tests = [
        "tests/test_corpus_authority_pg.py",
        "tests/test_corpus_negative_query.py",
        "tests/test_corpus_product_observations.py",
        "tests/test_corpus_search_pg.py",
        "tests/test_corpus_selection.py",
    ]
    evidence = [
        ".scratch/m6-retrieval-fix-20260923/product-summary.json",
        ".scratch/m6-retrieval-fix-20260923/product-raw-default-details.json",
        ".scratch/m6-retrieval-fix-20260923/report.md",
        ".scratch/m6-retrieval-fix-20260923/rebuild-report.json",
        ".scratch/m6-retrieval-fix-20260923/rebuild-report.md",
        ".scratch/m6-retrieval-fix-20260923/spec.md",
    ]
    state = [
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    ]
    previous = [".scratch/m6-retrieval-fix-20260923/previous-effective-bindings.json"]
    validator = [
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
    ]
    parent = FREEZES / "i0c-r5d.json"
    snapshot = {
        "snapshot_id": "i0c-r5e",
        "revision": "r5e",
        "phase": "i0c",
        "status": "frozen_product_acceptance_passed",
        "business_accepted": True,
        "parent_snapshot": {
            "snapshot_id": "i0c-r5d",
            "path": str(parent.relative_to(ROOT)),
            "sha256": digest(parent),
        },
        "binding": {
            "m6_retrieval_implementation": binding(implementation),
            "m6_retrieval_tests": binding(tests),
            "m6_retrieval_evidence": binding(evidence),
            "m6_retrieval_state": binding(state),
            "previous_effective_bindings": binding(previous),
            "freeze_validator": binding(validator),
        },
        "corrections": {
            "retrieval": "Natural questions use substantive OR candidates, source-title recall, and a source-diversified bounded pool.",
            "evidence": "Same-page bounded bands expose ordered authority context locators; semantic cells are checked against their unit spans.",
            "negative": "The default-on strict abstain gate applies only to explicit corpus-availability questions.",
        },
        "verification": {
            "product": {
                "queries": 30,
                "question_pass": [24, 24],
                "evidence_pass": [24, 24],
                "false_positives": 0,
                "tool_failures": 0,
            },
            "full_suite": {"passed": 2961, "failed": 2, "skipped": 17},
            "existing_failures": [
                "test_market_hit_rate_is_100_percent",
                "test_react_profile_binds_the_finance_tools",
            ],
            "postgres_authority": {"passed": 12},
            "postgres_search": {"passed": 11},
            "ruff_ci_paths": "passed",
            "pyright_errors": 0,
            "import_smoke": {"stage1": [365, 365], "stage2": [414, 414]},
            "missing_symbols": 0,
            "model_calls": 0,
        },
        "notes": [
            "Gold, scorer, threshold, raw product questions, and limit=10 are unchanged.",
            "All historical snapshots and r5d failure evidence remain byte-identical.",
            "Sandbox was restored to 8/8 published+active after destructive PG tests.",
            "No production 5432 access, held-out tuning, model preflight, or I4 action.",
        ],
        "m5_declaration": "not_changed",
    }
    write_json(SNAPSHOT, snapshot)
    rows.append(
        {
            "snapshot_id": "i0c-r5e",
            "file": "i0c-r5e.json",
            "sha256": digest(SNAPSHOT),
            "parent_snapshot_id": "i0c-r5d",
            "created_at": datetime.now().astimezone().isoformat(),
        }
    )
    write_json(INDEX, index)
    print("Appended i0c-r5e; historical snapshots unchanged; business_accepted=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
