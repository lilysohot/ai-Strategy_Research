"""Bind human review implementation, preserving actual pre-edit bytes and pending sign-off."""
from __future__ import annotations

from datetime import datetime, UTC
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
FREEZES = HERE.parents[1] / "freezes"
sys.path.insert(0, str(FREEZES))
from freeze_utils import digest

IMPL = ["plugins/corpus/preparation/gap_review.py", "plugins/corpus/preparation/gaps.py",
        "plugins/corpus/preparation/engine.py", "plugins/corpus/preparation/repository.py",
        "plugins/corpus/preparation/repository_pg.py", "plugins/corpus/cli.py"]
DOCS = ["docs/plan/corpus-ingestion-rebuild-architecture.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md", "docs/plan/claims-market-closed-loop-plan.md"]
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST = FREEZES / "freeze-manifest.json"
SNAPSHOT = FREEZES / "i0c-r36.json"


def mapping(paths):
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)}


def bind():
    archives = json.loads((HERE / "archives.json").read_text())
    for item in archives:
        if not item["matches_previous_binding"] or digest(ROOT / item["archived_as"]) != item["sha256"]:
            raise RuntimeError("pre-edit archive is not faithful")
    evidence = [p for p in HERE.iterdir() if p.is_file() and p.suffix in {".json", ".md", ".py", ".txt"}]
    # Guard-bound failure experiments are retained and labelled, not disguised as passing checks.
    data = {
        "snapshot_id": "i0c-r36", "revision": "r36", "phase": "i0c",
        "task": "I3-1 build-bound human gap review mechanism; no real sign-offs or publications",
        "status": "implemented_pending_human_review",
        "parent_snapshot": {"snapshot_id": "i0c-r35",
                            "path": str((FREEZES / "i0c-r35.json").relative_to(ROOT)),
                            "sha256": digest(FREEZES / "i0c-r35.json")},
        "binding": {
            "human_gap_implementation": mapping([ROOT / p for p in IMPL]),
            "human_gap_tests": mapping([ROOT / "tests/test_corpus_gap_review.py"]),
            "human_gap_docs": mapping([ROOT / p for p in DOCS]),
            "human_gap_evidence": mapping(evidence),
            "human_gap_archive": {item["archived_as"]: item["sha256"] for item in archives},
            "freeze_validator": mapping([VALIDATOR]),
        },
        "real_review_records_written": 0, "real_sources_published": 0,
        "per_class_min_2": False,
        "notes": [
            "User-selected mechanism only; no per-gap human approval was supplied or fabricated.",
            "Default grading table unchanged; gap-policy-2 versions the new adjudication path.",
            "No guard/gold/admission policy changes, no model calls, no source replacement.",
            "13 actual blockers remain. Same-page gold/gap overlap still fails closed.",
            "Generic import smoke was blocked by the unchanged I3 model-import guard; LLM preflight not run.",
        ],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    # Re-entrant byte-stable metadata within this revision; never mint new timestamps on a rerun.
    if SNAPSHOT.exists():
        data["created_at"] = json.loads(SNAPSHOT.read_text())["created_at"]
    SNAPSHOT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    manifest = json.loads(MANIFEST.read_text())
    entries = [item for item in manifest["snapshots"] if item["snapshot_id"] != "i0c-r36"]
    entries.append({"snapshot_id": "i0c-r36", "file": SNAPSHOT.name, "sha256": digest(SNAPSHOT),
                    "parent_snapshot_id": "i0c-r35", "created_at": data["created_at"]})
    manifest["snapshots"] = entries
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def gate(script):
    result = subprocess.run([sys.executable, "-B", str(script)], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return result.returncode, result.stdout + f"\nexit={result.returncode}\n"


if __name__ == "__main__":
    bind()
    for script, name in [(VALIDATOR, "freeze-validation.txt"),
                         (FREEZES / "validate_i3_2_completion.py", "i3-2-completion.txt")]:
        code, output = gate(script)
        (HERE / name).write_text(output)
        print(name, output[-3000:])
        if code:
            raise SystemExit(code)
    bind()
    code, output = gate(VALIDATOR)
    if code or output != (HERE / "freeze-validation.txt").read_text():
        raise RuntimeError("freeze verification after binding logs differs or fails: " + output)
    print("r36 binding and both completion gates verified; real human review still pending.")
