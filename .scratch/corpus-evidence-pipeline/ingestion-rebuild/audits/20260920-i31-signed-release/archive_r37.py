"""Archive pre-edit docs/validator; preserve user signatures at their original paths."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
FREEZES = BASE / "freezes"
sys.path.insert(0, str(FREEZES))
from freeze_utils import archive_first, assert_archives_faithful, digest

PATHS = ["docs/plan/corpus-ingestion-rebuild-tasks.md", "docs/plan/claims-market-closed-loop-plan.md",
         str((FREEZES / "validate_i0c_freeze.py").relative_to(ROOT)),
         str((FREEZES / "freeze-manifest.json").relative_to(ROOT))]

if __name__ == "__main__":
    records = archive_first(PATHS, HERE / "before-r37", root=ROOT, freezes_dir=FREEZES,
                            exclude=tuple(p.stem for p in FREEZES.glob("i1-*.json")))
    assert_archives_faithful(records)
    (HERE / "archives.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    snapshot = json.loads((FREEZES / "i0c-r36.json").read_text())
    recovered = []
    for short in ("6f14cc14", "174b6462", "793b3967", "dddc7cd0"):
        name = f"unsigned-{short}.json"
        prior_submission = BASE / "audits/20260920-i31-gap-review-submission/submitted-originals" / name
        value = json.loads(prior_submission.read_text())
        value.update(reviewer="", reviewed_at="")
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        import hashlib
        original = BASE / "audits/20260920-i31-human-gap-review" / name
        expected = snapshot["binding"]["human_gap_evidence"][str(original.relative_to(ROOT))]
        if hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError("Cannot reconstruct historical frozen template bytes")
        target = HERE / "r36-template-recovery" / name
        target.parent.mkdir(exist_ok=True)
        if target.exists() and target.read_bytes() != raw:
            raise RuntimeError("Historical recovery file differs")
        target.write_bytes(raw)
        recovered.append({"original_path": str(original.relative_to(ROOT)),
                          "historical_template_path": str(target.relative_to(ROOT)),
                          "sha256": digest(target),
                          "method": "Reconstructed from earlier submitted copy by clearing reviewer/reviewed_at; exact r36 SHA-256 match. Not claimed as pre-edit archive of latest signed user bytes.",
                          "current_signed_sha256": digest(original)})
    (HERE / "historical-template-recovery.json").write_text(json.dumps(recovered, ensure_ascii=False, indent=2) + "\n")
    print("Archived 4 pre-edit files; recovered 4 exact r36 templates separately. User signed paths unchanged.")
