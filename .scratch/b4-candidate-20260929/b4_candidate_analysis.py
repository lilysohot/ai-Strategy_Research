"""候选对照异常诊断：174b6462 p10 行序 + 6f14cc14/dddc7cd0 字符丢失定位。

A：候选 page 10 单元序列（ordinal/bbox/status/raw）+ 5 条 gold 引文的连续性断裂定位。
B：旧（PG 基线单元）相对新（reader-pdf-8 重读）的字符赤字定位——逐旧单元核对其
   文本是否仍存在于新文档（连续/乱序/缺失），区分良性去重与真实丢失。
隔离同 B4：零模型、PG 只读、纯内存。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

spec = importlib.util.spec_from_file_location(
    "b1_comparison", ROOT / ".scratch/b1-comparison-20260929/b1_comparison.py"
)
b1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1)
b0 = b1.b0

import psycopg  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402
from b4_candidate import ARCHIVE, build_candidate_artifacts, norm  # noqa: E402

FOCUS = ["2026-08-13_174b6462", "2026-08-16_6f14cc14", "2026-09-06_dddc7cd0"]
QUOTES_P10 = {
    "industry-001/e4": "纯碱\n0.0%\n0.0%\n82.9%",
    "industry-001/e5": "24.0\n28.5\n28.5\n-\n18.8%\n0.0%",
    "industry-003/a-3": "产能（万吨/年）以及同比增长\n产品\n表观消费量（万吨）以及同比增长\n价格分位\n价差分位\n开工率",
    "industry-003/e3": "尿素\n32.1%\n10.9%\n89.9%",
    "industry-008/a-2": "产能（万吨/年）以及同比增长\n产品\n表观消费量（万吨）以及同比增长\n价格分位\n价差分位\n开工率",
}


def main() -> None:
    with psycopg.connect(dsn()) as conn:
        conn.execute("SET default_transaction_read_only=on")
        resolved = b0.resolve_sources(conn, set(FOCUS))
        old_arts: dict[str, dict] = {}
        arch_paths: dict[str, str] = {}
        for gid in FOCUS:
            full = resolved[gid]["corpus_source_id"]
            assert full, gid
            old_arts[full] = b0.load_source_artifacts(conn, resolved[gid]["build_id"])
            row = conn.execute(
                "SELECT archive_path FROM corpus.corpus_sources WHERE source_id=%s", (full,)
            ).fetchone()
            arch_paths[full] = row[0]

    new_arts = {
        gid: build_candidate_artifacts(
            ARCHIVE / arch_paths[resolved[gid]["corpus_source_id"]], resolved[gid]["corpus_source_id"], resolved[gid]["build_id"]
        )
        for gid in FOCUS
    }

    result: dict = {"p10": {}, "char_diff": {}}

    # ── A：174b6462 page 10 ──
    art = new_arts["2026-08-13_174b6462"]
    p10_units = [
        {
            "unit_id": u["unit_id"],
            "bbox": u["bbox"],
            "status": u["status"],
            "n_cells": u["n_cells"],
            "raw": u["raw"],
        }
        for u in art["units"]
        if u["page"] == "10"
    ]
    result["p10"]["units"] = p10_units
    result["p10"]["quotes"] = {}
    for label, quote in QUOTES_P10.items():
        qn = norm(quote)
        pos = art["doc_norm"].find(qn)
        entry = {"in_concat": pos >= 0, "pos": pos}
        if pos < 0:
            # 逐 token 定位：token 在 doc_norm 中的位置序列 → 断裂处插入了什么
            toks = [norm(t) for t in re.split(r"\s+", quote.strip()) if t]
            positions = []
            cursor = 0
            for tok in toks:
                i = art["doc_norm"].find(tok, cursor)
                positions.append({"tok": tok[:12], "at": i})
                if i >= 0:
                    cursor = i + len(tok)
            gaps = []
            for a, b in zip(positions, positions[1:]):
                if b["at"] < 0 or a["at"] < 0:
                    continue
                between = art["doc_norm"][a["at"] + len(a["tok"]) : b["at"]]
                if between:
                    gaps.append({"after": a["tok"][:12], "inserted": between[:60]})
            entry["gaps"] = gaps
        result["p10"]["quotes"][label] = entry

    # ── B：字符赤字定位 ──
    for gid in FOCUS:
        full = resolved[gid]["corpus_source_id"]
        old, new = old_arts[full], new_arts[gid]
        old_norm, new_norm = old["doc_norm"], new["doc_norm"]
        deficit = {
            ch: old_norm.count(ch) - new_norm.count(ch)
            for ch in set(old_norm)
            if old_norm.count(ch) > new_norm.count(ch)
        }
        missing_units = []
        for u in old["units"]:
            if not u["norm"] or u["norm"] in new_norm:
                continue
            # 逐 token 核对：文本是否散落在新文档（乱序）还是真缺失
            toks = [t for t in re.split(r"\s+", (u["raw"] or "").strip()) if len(t) >= 2]
            present = [norm(t) in new_norm for t in toks]
            missing_units.append(
                {
                    "unit_id": u["unit_id"],
                    "page": u["page"],
                    "element": u["element"],
                    "raw_head": (u["raw"] or "")[:80],
                    "raw_len": len(u["raw"] or ""),
                    "tokens_total": len(toks),
                    "tokens_missing": present.count(False),
                }
            )
        result["char_diff"][gid] = {
            "deficit_total": sum(deficit.values()),
            "deficit_top": dict(sorted(deficit.items(), key=lambda kv: -kv[1])[:20]),
            "old_units": len(old["units"]),
            "new_units": len(new["units"]),
            "units_not_contiguous": len(missing_units),
            "missing_units": missing_units,
        }

    (OUT / "analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(dsn(), "<REDACTED>"),
        encoding="utf-8",
    )
    # 摘要
    for gid, d in result["char_diff"].items():
        print(f"\n=== {gid}: deficit={d['deficit_total']} units_not_contiguous={d['units_not_contiguous']} (old {d['old_units']} → new {d['new_units']})")
        print("deficit_top:", json.dumps(d["deficit_top"], ensure_ascii=False))
        for m in d["missing_units"][:12]:
            print(f"  {m['unit_id']} p{m['page']} {m['element']} len={m['raw_len']} tok_missing={m['tokens_missing']}/{m['tokens_total']} :: {m['raw_head']!r}")
    print("\n=== P10 quotes ===")
    for label, e in result["p10"]["quotes"].items():
        print(label, "in_concat" if e["in_concat"] else "BROKEN", json.dumps(e.get("gaps", []), ensure_ascii=False))


if __name__ == "__main__":
    main()
