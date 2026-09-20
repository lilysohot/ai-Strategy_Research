"""Freeze bounded calibration results without treating failed candidates as passed."""
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
SNAPSHOT = FREEZES / "i0c-r39.json"


def mapping(paths):
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}


def bind():
    archives = json.loads((HERE / "archives.json").read_text())
    assert all(i["matches_previous_binding"] and digest(ROOT / i["archived_as"]) == i["sha256"] for i in archives)
    data = {
        "snapshot_id": "i0c-r39", "revision": "r39", "phase": "i0c", "status": "i33_calibrating_two_failed_runs_filed",
        "parent_snapshot": {"snapshot_id": "i0c-r38", "path": str((FREEZES / "i0c-r38.json").relative_to(ROOT)),
                            "sha256": digest(FREEZES / "i0c-r38.json")},
        "binding": {
            "calibration_evidence": mapping([p for p in HERE.iterdir() if p.is_file() and p.suffix in {".json", ".py", ".md", ".txt"}]),
            "calibration_docs": mapping([ROOT / "docs/plan" / p for p in (
                "corpus-ingestion-rebuild-tasks.md", "claims-market-closed-loop-plan.md")]),
            "calibration_archive": {i["archived_as"]: i["sha256"] for i in archives},
            "freeze_validator": mapping([VALIDATOR]),
        },
        "i31_complete": True, "i33_complete": False, "m6_released": False,
        "model_calls": 0, "calibration_runs": 2, "question_count": 30,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if SNAPSHOT.exists():
        data["created_at"] = json.loads(SNAPSHOT.read_text())["created_at"]
    SNAPSHOT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    manifest = json.loads(MANIFEST.read_text())
    manifest["snapshots"] = [i for i in manifest["snapshots"] if i["snapshot_id"] != "i0c-r39"]
    manifest["snapshots"].append({"snapshot_id": "i0c-r39", "file": SNAPSHOT.name, "sha256": digest(SNAPSHOT),
                                  "parent_snapshot_id": "i0c-r38", "created_at": data["created_at"]})
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def gate(script):
    result = subprocess.run([sys.executable, "-B", str(script)], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    return result.returncode, result.stdout + f"\nexit={result.returncode}\n"


if __name__ == "__main__":
    bind()
    for script, name in [(VALIDATOR, "freeze-validation.txt"),
                         (FREEZES / "validate_i3_2_completion.py", "i3-2-completion.txt"),
                         (HERE / "verify_calibration.py", "calibration-replay.txt")]:
        code, output = gate(script)
        (HERE / name).write_text(output)
        print(name, "exit", code, output[-400:] if not code else output)
        if code:
            raise SystemExit(code)
    bind()
    code, output = gate(VALIDATOR)
    assert code == 0 and output == (HERE / "freeze-validation.txt").read_text(), output
    print("r39 verified; I3-1 complete, I3-3 in progress, failed scores retained.")
