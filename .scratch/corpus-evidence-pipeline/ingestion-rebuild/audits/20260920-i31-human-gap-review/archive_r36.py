"""Archive live bytes before implementing the user-selected human gap review path."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
FREEZES = HERE.parents[1] / "freezes"
sys.path.insert(0, str(FREEZES))
from freeze_utils import archive_first, assert_archives_faithful, merged_binding

PATHS = [
    "plugins/corpus/preparation/gaps.py",
    "plugins/corpus/preparation/engine.py",
    "plugins/corpus/preparation/repository.py",
    "plugins/corpus/preparation/repository_pg.py",
    "plugins/corpus/cli.py",
    "docs/plan/corpus-ingestion-rebuild-architecture.md",
    "docs/plan/corpus-ingestion-rebuild-tasks.md",
    "docs/plan/claims-market-closed-loop-plan.md",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/freeze-manifest.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
]
if __name__ == "__main__":
    # Match the validator's effective precedence: I0-C revisions supersede old I1
    # bindings (r35 already documents this legacy helper ordering pitfall).
    older = merged_binding(FREEZES)
    i1 = tuple(path.stem for path in FREEZES.glob("i1-*.json"))
    current = {**older, **merged_binding(FREEZES, exclude=i1)}
    records = archive_first(
        PATHS, HERE / "before-r36", root=ROOT, freezes_dir=FREEZES, exclude=i1
    )
    for record in records:
        expected = current.get(record["path"])
        record["matches_previous_binding"] = expected is None or expected == record["sha256"]
    assert_archives_faithful(records)
    (HERE / "archives.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"Archived {len(records)} paths; all match preceding bindings.")
