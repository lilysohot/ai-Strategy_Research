"""r5l archive-first：只重绑 ruff I001 修正的测试与扩展验证器。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
WINDOW = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
TEST = "tests/test_corpus_ingest_retired.py"
VALIDATOR = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    r5k = json.loads((FREEZES / "i0c-r5k.json").read_text(encoding="utf-8"))
    previous = {
        TEST: r5k["binding"]["m7_rereview_tests"][TEST],
        VALIDATOR: r5k["binding"]["freeze_validator"][VALIDATOR],
    }
    before = WINDOW / "before-r5l"
    if before.exists():
        import shutil

        shutil.rmtree(before)
    # r5l 只把 imports 排序；由当前字节逆变换还原 r5k 已绑定的精确前任。
    prior_test = (ROOT / TEST).read_bytes().replace(
        b"import inspect\nimport json\n", b"import json\nimport inspect\n", 1
    )
    for rel, source in ((TEST, prior_test), (VALIDATOR, ROOT / VALIDATOR)):
        target = before / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source if isinstance(source, bytes) else source.read_bytes())
        if digest(target) != previous[rel]:
            raise SystemExit(f"archive mismatch: {rel}")
    prev = WINDOW / "previous-effective-bindings-r5l.json"
    prev.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
