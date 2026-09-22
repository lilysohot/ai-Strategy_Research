"""A-1：把 industry-009-claim-001 的两条 `col:`/`cell:` 改成原文可派生口径。

背景（只读核实，见 e2-col-probe.json）：
  - 原文 page:10 的列组为「产能（万吨/年）以及同比增长 = 2024/2025/2026E」；
    R32 行 = 24.0/28.5/28.5（2026E=28.5 ✓）、尿素行 = 7696.0/7956.0/8068.0（2026E=8068.0 ✓）。
  - 金标值正确，仅 `col:` 写成人工合成列名（机器不可派生）；
    反事实探针给出唯一可派生候选 = `col:产能（万吨/年）以及同比增长`。

改动（文本级精确替换，只动目标行，不重序列化其它行）：
  col : "2026E产能（配额）" → "产能（万吨/年）以及同比增长"     (row=R32)
  cell: "R32 × 2026E产能（配额）" → "R32 × 产能（万吨/年）以及同比增长"
  col : "2026E产能"         → "产能（万吨/年）以及同比增长"     (row=尿素)
  cell: "尿素 × 2026E产能"  → "尿素 × 产能（万吨/年）以及同比增长"

不动：quote / row / unit / period / kind / text（text 为人工陈述句，不参与判定，
     是否同步改写由 U 另行决定）。

用法： uv run python apply_source_gold_col_fix.py [--no-write]
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
SOURCE_GOLD = INGEST / "source-gold-frozen.jsonl"
GOLD_ID = "industry-009-claim-001"
NEW_COL = "产能（万吨/年）以及同比增长"

REPLACEMENTS = (
    ('"col": "2026E产能（配额）"', f'"col": "{NEW_COL}"'),
    ('"cell": "R32 × 2026E产能（配额）"', f'"cell": "R32 × {NEW_COL}"'),
    ('"col": "2026E产能"', f'"col": "{NEW_COL}"'),
    ('"cell": "尿素 × 2026E产能"', f'"cell": "尿素 × {NEW_COL}"'),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    raw = SOURCE_GOLD.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    hits: dict[str, int] = {}
    changed = 0

    for idx, line in enumerate(lines):
        if GOLD_ID not in line:
            continue
        new = line
        for old, rep in REPLACEMENTS:
            n = new.count(old)
            if n:
                hits[old] = hits.get(old, 0) + n
                new = new.replace(old, rep)
        if new != line:
            lines[idx] = new
            changed += 1

    if changed != 1:
        raise RuntimeError(f"目标行匹配数异常：changed={changed}（应为 1）")
    for old, _rep in REPLACEMENTS:
        if hits.get(old, 0) != 1:
            raise RuntimeError(f"替换次数异常：{old!r} × {hits.get(old, 0)}（应为 1）")

    out = "".join(lines)
    print("before sha256:", digest(SOURCE_GOLD))
    print("替换统计:", {k: v for k, v in hits.items()})
    print("改动行数:", changed)

    if args.no_write:
        import difflib
        diff = list(difflib.unified_diff(
            raw.splitlines(), out.splitlines(), "before", "after", lineterm="", n=0))
        print("\n".join(diff[:40]))
        print("[--no-write] 未写盘")
        return 0

    SOURCE_GOLD.write_text(out, encoding="utf-8")
    print("after  sha256:", digest(SOURCE_GOLD))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
