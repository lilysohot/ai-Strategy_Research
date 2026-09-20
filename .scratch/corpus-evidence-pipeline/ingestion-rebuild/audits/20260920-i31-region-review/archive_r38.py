import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
FREEZES = BASE / "freezes"
sys.path.insert(0, str(FREEZES))
from freeze_utils import archive_first, assert_archives_faithful

paths = ["plugins/corpus/preparation/gap_review.py", "plugins/corpus/preparation/gaps.py",
         "plugins/corpus/preparation/repository.py", "plugins/corpus/preparation/engine.py",
         "tests/test_corpus_gap_review.py", "docs/plan/corpus-ingestion-rebuild-architecture.md",
         "docs/plan/corpus-ingestion-rebuild-tasks.md", "docs/plan/claims-market-closed-loop-plan.md",
         str((FREEZES / "validate_i0c_freeze.py").relative_to(ROOT)),
         str((FREEZES / "freeze-manifest.json").relative_to(ROOT))]
records = archive_first(paths, HERE / "before-r38", root=ROOT, freezes_dir=FREEZES,
                        exclude=tuple(p.stem for p in FREEZES.glob("i1-*.json")))
assert_archives_faithful(records)
(HERE / "archives.json").write_text(json.dumps(records, indent=2) + "\n")
print("Pre-edit archives verified:", len(records))
