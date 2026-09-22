"""A-3：审批件 based_on 重绑（上游 source-gold / candidates 哈希随 A-1/A-2 变化）。

不改任何决定内容（40 项 facet_decisions / 24 项 question_reviews / 6 项 negative_reviews
/ 1 项 human_status_clarifications 一律不动），只做两件事：
  1. `based_on.candidates_sha256` / `based_on.source_gold_sha256` 更新为当前实际值；
  2. `adoption_note` 末尾追加本次重绑的留痕（依据 + 授权 + 改动范围）。

用法： uv run python apply_decisions_rebind.py [--no-write]
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
DECISIONS = INGEST / "i3-2/evidence-targets-decisions.json"
SOURCE_GOLD = INGEST / "source-gold-frozen.jsonl"
CANDIDATES = INGEST / "i3-2/evidence-targets-candidates.json"

OLD_CANDIDATES = "7d4a1c76d96a9205ae80224b184d5efdaa273af35c0008ba188ecf6a543c74f8"
OLD_SOURCE_GOLD = "37662c77a76caa3e86a7f8480a1a7b4978ccc367e0b6e367fd5c5c7dc2ec2adc"
NOTE_ANCHOR = "供后续审计区分「人工判断」与「AI 辅助」。"
NOTE_APPEND = (
    "2026-09-23 U 具名授权重绑：source-gold 的 industry-009-claim-001 两条 col/cell 由人工合成列名"
    "（2026E产能（配额）/2026E产能）改为原文可派生口径「产能（万吨/年）以及同比增长」，"
    "quote/row/unit/period/text 一律不动；依据＝原 PDF 第 10 页 ord529（尿素 7696.0/7956.0/8068.0）"
    "与 ord563（R32 24.0/28.5/28.5）列组与取值机读核对，加反事实探针 "
    "audits/20260923-b5-e2-col-probe/e2-col-probe.json（唯一可派生候选）。"
    "本件各项决定内容不变，仅 based_on 随上游哈希更新。"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    new_candidates = digest(CANDIDATES)
    new_source_gold = digest(SOURCE_GOLD)
    raw = DECISIONS.read_text(encoding="utf-8")

    for old in (OLD_CANDIDATES, OLD_SOURCE_GOLD, NOTE_ANCHOR):
        if old not in raw:
            raise RuntimeError(f"锚点缺失，文件已被改动: {old[:24]}…")

    out = raw.replace(OLD_CANDIDATES, new_candidates, 1)
    out = out.replace(OLD_SOURCE_GOLD, new_source_gold, 1)
    out = out.replace(NOTE_ANCHOR, NOTE_ANCHOR + NOTE_APPEND, 1)

    if OLD_CANDIDATES in out or OLD_SOURCE_GOLD in out:
        raise RuntimeError("旧哈希未完全替换")

    print("candidates :", OLD_CANDIDATES[:12], "→", new_candidates[:12])
    print("source_gold:", OLD_SOURCE_GOLD[:12], "→", new_source_gold[:12])
    print("adoption_note 追加:", len(NOTE_APPEND), "字符")

    if args.no_write:
        print("[--no-write] 未写盘（decisions sha256 保持 "
              f"{digest(DECISIONS)[:12]}）")
        return 0

    DECISIONS.write_text(out, encoding="utf-8")
    print("decisions 新 sha256:", digest(DECISIONS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
