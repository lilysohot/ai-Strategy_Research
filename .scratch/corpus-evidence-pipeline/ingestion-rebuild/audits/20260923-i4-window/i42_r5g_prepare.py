"""I4-2 / r5g 前置：**archive-first**——任何代码改动之前执行。

产出（write-once，仅当全部检查通过时写出）：

1. ``previous-effective-bindings-r5g.json``：9 个改前路径的**生效绑定哈希**
   （按验证器 section 顺序 last-writer-wins 提取，即 merge_binding 语义）；
2. ``before-r5g/<path>``：9 个路径的改前字节归档；
3. ``i42-r5g-archive.json``：归档台账 + 不变量检查。

不变量（必须全绿才允许写盘）：

- 非漂移路径（6 代码 + 验证器）：prior 生效绑定 == 当前磁盘字节（验证器当前对它们 green）；
- 两份 docs（README.md / tasks.md）：prior != 磁盘（r5f 后 I4-1 §0 回填导致的已知漂移，
  r4z 先例——本次重绑的对象）；
- ``pg_target.py`` 尚不存在（r5g 新文件，first-in-chain）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
FREEZES = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
AUD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"

VALIDATOR_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"
DRIFT_EXPECTED = {"docs/plan/README.md", "docs/plan/corpus-ingestion-rebuild-tasks.md"}

# 与 validate_i0c_freeze.py 的 section 顺序一致：数值修订升序，随后 r4n..r4z、r5a..r5f。
ORDER = [f"i0c-r{n}" for n in range(2, 44)] + [
    "i0c-r4n", "i0c-r4p", "i0c-r4q", "i0c-r4r", "i0c-r4s", "i0c-r4t",
    "i0c-r4u", "i0c-r4v", "i0c-r4w", "i0c-r4x", "i0c-r4y", "i0c-r4z",
    "i0c-r5a", "i0c-r5b", "i0c-r5c", "i0c-r5d", "i0c-r5e", "i0c-r5f",
]

PATHS = [
    "plugins/corpus/preparation/pg_target.py",  # r5g 新文件：无 prior 绑定，不归档
    "plugins/corpus/preparation/repository_pg.py",
    "plugins/corpus/preparation/read_pg.py",
    "plugins/corpus/preparation/search_pg.py",
    "plugins/corpus/preparation/cross_boundary.py",
    "plugins/corpus/service.py",
    "plugins/corpus/cli.py",
    VALIDATOR_REL,
    "docs/plan/README.md",
    "docs/plan/corpus-ingestion-rebuild-tasks.md",
]
OLD = [p for p in PATHS if p != "plugins/corpus/preparation/pg_target.py"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    prior: dict[str, str] = {}
    for sid in ORDER:
        snap = FREEZES / f"{sid}.json"
        if not snap.is_file():
            continue
        data = json.loads(snap.read_text(encoding="utf-8"))
        for items in (data.get("binding") or {}).values():
            for rel, expected in items.items():
                prior[rel] = expected

    checks: list[dict[str, object]] = []

    def chk(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    chk("pg_target.py 尚不存在", not (ROOT / "plugins/corpus/preparation/pg_target.py").exists())
    for rel in OLD:
        disk = digest(ROOT / rel)
        bound = prior.get(rel)
        if rel in DRIFT_EXPECTED:
            chk(f"docs 漂移符合预期（prior != 磁盘）: {rel}", bound != disk, f"prior={bound} disk={disk}")
        else:
            chk(f"非漂移路径 prior == 磁盘: {rel}", bound == disk, f"prior={bound} disk={disk}")

    failed = [c for c in checks if not c["ok"]]
    for c in checks:
        print(("OK  " if c["ok"] else "FAIL") + f" {c['check']}" + (f" | {c['detail']}" if c["detail"] else ""))
    if failed:
        print(f"ABORT：{len(failed)} 项检查未过，不写任何产物")
        return 1

    before = AUD / "before-r5g"
    archive: list[dict[str, object]] = []
    for rel in OLD:
        src = ROOT / rel
        dst = before / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        d = digest(dst)
        archive.append(
            {
                "path": rel,
                "sha256": d,
                "matches_prior_effective": d == prior[rel],
                "drift_expected": rel in DRIFT_EXPECTED,
            }
        )
    archive.append(
        {
            "path": "plugins/corpus/preparation/pg_target.py",
            "sha256": None,
            "matches_prior_effective": None,
            "drift_expected": False,
            "note": "r5g 新文件（first-in-chain），无 prior 绑定，不归档",
        }
    )

    payload = {
        "purpose": "I4-2 r5g archive-first 台账：改动前归档 + 改前生效绑定提取",
        "order_note": (
            "prior 生效绑定按 validate_i0c_freeze.py 的 section 顺序 last-writer-wins 提取"
            "（r2..r43 数值序，随后 r4n..r4z、r5a..r5f），与 merge_binding 语义一致"
        ),
        "prior_effective": {rel: prior[rel] for rel in OLD},
        "checks": checks,
        "archive": archive,
    }
    (AUD / "i42-r5g-archive.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (AUD / "previous-effective-bindings-r5g.json").write_text(
        json.dumps({rel: prior[rel] for rel in OLD}, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print("r5g 前置完成：before-r5g 归档 + previous-effective-bindings-r5g.json 已写盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
