"""r5k archive-first：归档所有将被 M7 二次复核修订覆盖的有效字节。"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
WINDOW = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
CHANGED = [
    "plugins/corpus/service.py",
    "tests/test_corpus_ingest_retired.py",
    "tests/test_corpus_evidence_pipeline.py",
    "tests/test_corpus_authority_pg.py",
    "tests/test_corpus_claims_interface.py",
    "docs/plan/corpus-ingestion-rebuild-tasks.md",
    VALIDATOR,
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def old_bytes(rel: str) -> bytes:
    proc = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, check=False)
    if proc.returncode:
        raise SystemExit(f"cannot archive {rel}: {proc.stderr.decode()[:200]}")
    return proc.stdout


def effective_bindings() -> dict[str, str]:
    manifest = json.loads((FREEZES / "freeze-manifest.json").read_text(encoding="utf-8"))
    current: dict[str, str] = {}
    for entry in manifest["snapshots"]:
        if not str(entry["snapshot_id"]).startswith("i0c-r"):
            continue
        snapshot = json.loads((FREEZES / entry["file"]).read_text(encoding="utf-8"))
        for items in snapshot.get("binding", {}).values():
            current.update(items)
    return current


def main() -> int:
    prior = effective_bindings()
    before = WINDOW / "before-r5k"
    if before.exists():
        raise SystemExit(f"archive already exists: {before}")
    previous = {rel: prior[rel] for rel in CHANGED}
    for rel in CHANGED:
        data = old_bytes(rel)
        if digest(data) != previous[rel]:
            raise SystemExit(f"HEAD bytes are not the prior effective binding: {rel}")
        target = before / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    prev_path = WINDOW / "previous-effective-bindings-r5k.json"
    prev_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"archived": CHANGED, "previous": str(prev_path.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
