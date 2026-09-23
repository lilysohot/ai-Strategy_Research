"""Append the validator-only r5f supersession without rewriting r5e."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
INDEX = FREEZES / "freeze-manifest.json"
SNAPSHOT = FREEZES / "i0c-r5f.json"
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = index["snapshots"]
    if any(row["snapshot_id"] == "i0c-r5f" for row in rows) or SNAPSHOT.exists():
        raise RuntimeError("i0c-r5f already exists; append a new revision instead")
    if not rows or rows[-1]["snapshot_id"] != "i0c-r5e":
        raise RuntimeError("i0c-r5f must append directly after i0c-r5e")
    for row in rows:
        if digest(FREEZES / row["file"]) != row["sha256"]:
            raise RuntimeError(f"historical snapshot drift: {row['snapshot_id']}")

    parent = FREEZES / "i0c-r5e.json"
    parent_data = json.loads(parent.read_text(encoding="utf-8"))
    previous_validator = parent_data["binding"]["freeze_validator"][VALIDATOR]
    created_at = datetime.now().astimezone().isoformat()
    snapshot = {
        "snapshot_id": "i0c-r5f",
        "revision": "r5f",
        "phase": "i0c",
        "status": "frozen_validator_supersession",
        "business_accepted": True,
        "parent_snapshot": {
            "snapshot_id": "i0c-r5e",
            "path": str(parent.relative_to(ROOT)),
            "sha256": digest(parent),
        },
        "supersedes_validator_sha256": previous_validator,
        "binding": {"freeze_validator": {VALIDATOR: digest(ROOT / VALIDATOR)}},
        "correction": (
            "Treat r4v retrieval bytes as historical after r5e and resolve r39/r42 "
            "supersession against the r5e search implementation."
        ),
        "created_at": created_at,
    }
    write_json(SNAPSHOT, snapshot)
    rows.append(
        {
            "snapshot_id": "i0c-r5f",
            "file": SNAPSHOT.name,
            "sha256": digest(SNAPSHOT),
            "parent_snapshot_id": "i0c-r5e",
            "created_at": created_at,
        }
    )
    write_json(INDEX, index)
    print("Appended i0c-r5f; r5e product acceptance retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
