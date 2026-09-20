"""Freeze the signed release without rewriting user inputs or historical snapshots."""
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
FREEZES = HERE.parents[1] / "freezes"
sys.path.insert(0, str(FREEZES))
from freeze_utils import digest

VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST = FREEZES / "freeze-manifest.json"
SNAPSHOT = FREEZES / "i0c-r37.json"
PREVIOUS = HERE.parent / "20260920-i31-human-gap-review"


def mapping(paths):
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}


def bind():
    archives = json.loads((HERE / "archives.json").read_text())
    for item in archives:
        if not item["matches_previous_binding"] or digest(ROOT / item["archived_as"]) != item["sha256"]:
            raise RuntimeError("pre-edit archive mismatch")
    evidence = [p for p in HERE.iterdir() if p.is_file() and p.suffix in {".json", ".md", ".py", ".txt"}]
    for name in ("submitted", "r36-template-recovery"):
        evidence.extend((HERE / name).glob("*.json"))
    data = {
        "snapshot_id": "i0c-r37", "revision": "r37", "phase": "i0c",
        "task": "I3-1 adopt completed human signatures and publish three sources",
        "status": "signed_release_partial_with_i31_e2e_gates_passed",
        "parent_snapshot": {"snapshot_id": "i0c-r36",
                            "path": str((FREEZES / "i0c-r36.json").relative_to(ROOT)),
                            "sha256": digest(FREEZES / "i0c-r36.json")},
        "binding": {
            "i31_signed_inputs": mapping([PREVIOUS / f"unsigned-{short}.json"
                                          for short in ("6f14cc14", "174b6462", "793b3967", "dddc7cd0")]),
            "i31_release_evidence": mapping(evidence),
            "i31_release_docs": mapping([ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md",
                                          ROOT / "docs/plan/claims-market-closed-loop-plan.md"]),
            "i31_release_archive": {item["archived_as"]: item["sha256"] for item in archives},
            "freeze_validator": mapping([VALIDATOR]),
        },
        "real_review_records_written": 3, "new_sources_published": 3,
        "total_sources_published": 7, "total_sources": 8,
        "human_acknowledged": 12, "remaining_blocking": 1,
        "per_class_min_2": True, "format_gate": True, "model_calls": 0,
        "notes": [
            "All four human submissions are complete and preserved byte-for-byte at original paths.",
            "Guangli page 7 remains blocked by page-only coordinate validation, not a missing signature.",
            "Default dispositions, claimed scope, guards, source-gold, admission and implementation unchanged.",
            "Coverage remains scoped; I3-1 counts, formats and real E2E pass; M6/I4 not released.",
            "Historical r36 templates are explicitly reconstructed and verified against original frozen hashes.",
        ],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if SNAPSHOT.exists():
        data["created_at"] = json.loads(SNAPSHOT.read_text())["created_at"]
    SNAPSHOT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    manifest = json.loads(MANIFEST.read_text())
    manifest["snapshots"] = [item for item in manifest["snapshots"] if item["snapshot_id"] != "i0c-r37"]
    manifest["snapshots"].append({"snapshot_id": "i0c-r37", "file": SNAPSHOT.name,
                                  "sha256": digest(SNAPSHOT), "parent_snapshot_id": "i0c-r36",
                                  "created_at": data["created_at"]})
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
        print(name, output[-4000:])
        if code:
            raise SystemExit(code)
    bind()
    code, output = gate(VALIDATOR)
    if code or output != (HERE / "freeze-validation.txt").read_text():
        raise RuntimeError("post-binding verification changed or failed: " + output)
    print("r37 verified; user signatures preserved; 12 acknowledged, 1 coordinate-limited blocker retained.")
