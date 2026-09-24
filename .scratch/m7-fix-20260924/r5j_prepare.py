"""r5j Phase A（archive-first 准备）：归档改前生效字节 + 平铺 previous-effective-bindings。

- before-r5j/ 归档：
  - 5 个修复代码文件 + test_corpus_consumers_pg.py：取 ``git show HEAD:<path>``
    字节（已验证 == 链上最新生效绑定：代码=r5g 绑定、测试=r4s 绑定 24c65f47）；
  - validate_i0c_freeze.py：取当前磁盘字节（== r5i 绑定 c9e46bf9，扩展 r5j 节前）；
  - tasks.md 由 Phase C 回填后拷贝（drift 路径：归档字节即重绑来源，r5g 先例）。
- previous-effective-bindings-r5j.json：平铺 r5j 将重绑的**改前生效哈希**
  （5 代码 + 1 测试 + tasks.md + validator），全部从链文件读取，不手抄。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
WIN = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"
FRZ = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"

CODE = [
    "plugins/corpus/service.py",
    "plugins/corpus/preparation/read_pg.py",
    "plugins/corpus/preparation/search_pg.py",
    "plugins/corpus/preparation/cross_boundary.py",
    "plugins/corpus/cli.py",
]
TEST = "tests/test_corpus_consumers_pg.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(path: str) -> bytes:
    out = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True)
    if out.returncode != 0:
        raise SystemExit(f"git show failed: {path}: {out.stderr.decode()[:200]}")
    return out.stdout


def main() -> int:
    # 1) 归档目录（先清残留，保证幂等重建）
    before = WIN / "before-r5j"
    if before.exists():
        import shutil

        shutil.rmtree(before)
    for rel in [*CODE, TEST]:
        dest = before / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(git_blob(rel))
    validator_archive = before / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
    validator_archive.parent.mkdir(parents=True, exist_ok=True)
    validator_archive.write_bytes((FRZ / "validate_i0c_freeze.py").read_bytes())

    # 2) previous-effective-bindings-r5j.json（平铺，全部取自链文件）
    r5g = json.loads((FRZ / "i0c-r5g.json").read_text(encoding="utf-8"))
    r4s = json.loads((FRZ / "i0c-r4s.json").read_text(encoding="utf-8"))
    r5i = json.loads((FRZ / "i0c-r5i.json").read_text(encoding="utf-8"))
    prev: dict[str, str] = {}
    prev.update(r5g["binding"]["i4_window_target_adapter"])  # 5 代码文件改前生效哈希
    prev.pop("plugins/corpus/preparation/pg_target.py", None)  # pg_target 未被本次触碰
    prev.update(r4s["binding"]["chain_rebind_tests"])  # test_corpus_consumers_pg.py
    prev = {
        k: v
        for k, v in prev.items()
        if k in {*CODE, TEST}
    }
    prev["docs/plan/corpus-ingestion-rebuild-tasks.md"] = r5i["binding"]["i4_phase2_state"][
        "docs/plan/corpus-ingestion-rebuild-tasks.md"
    ]
    prev[".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"] = (
        r5i["binding"]["freeze_validator"][
            ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
        ]
    )

    # 一致性断言：归档字节 == 平铺声明哈希
    assert digest(validator_archive) == prev[
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
    ], "validator archive != r5i binding"
    for rel in [*CODE, TEST]:
        assert digest(before / rel) == prev[rel], f"archive != bound: {rel}"

    prev_path = WIN / "previous-effective-bindings-r5j.json"
    prev_path.write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"archived": sorted(str(p.relative_to(before)) for p in before.rglob("*") if p.is_file()),
                      "previous_effective_bindings": prev_path.name,
                      "entries": sorted(prev)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
