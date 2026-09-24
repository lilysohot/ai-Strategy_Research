"""r5m archive-first：恢复旧读审计的空表结构，不恢复 evidence 写入口。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
WINDOW = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    r5l = json.loads((FREEZES / "i0c-r5l.json").read_text(encoding="utf-8"))
    previous = {VALIDATOR: r5l["binding"]["freeze_validator"][VALIDATOR]}
    before = WINDOW / "before-r5m"
    if before.exists():
        import shutil

        shutil.rmtree(before)
    validator = (ROOT / VALIDATOR).read_bytes().replace(
        b'          and "raise RetiredEvidenceWriteError" in service5k,\n',
        b'          and "raise RetiredEvidenceWriteError" in service5k\n'
        b'          and "EVIDENCE_RUNS_SQL" not in service5k,\n',
        1,
    )
    for rel, data in ((VALIDATOR, validator),):
        target = before / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if digest(data) != previous[rel]:
            raise SystemExit(f"archive mismatch: {rel}")
    prev = WINDOW / "previous-effective-bindings-r5m.json"
    prev.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
