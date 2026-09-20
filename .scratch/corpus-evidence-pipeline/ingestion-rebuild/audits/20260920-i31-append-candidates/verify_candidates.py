"""I3-1 追加候选料只读复核（本地读取器 + 缺口裁决，零 PG / 零模型 / 零网络 / 不写冻结件）。

用途：在动任何 PG / 冻结链之前，先确认"追加 2 份已准入研报"这条简化路线今天仍然成立。
命令：uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-append-candidates/verify_candidates.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]

CANDIDATES = (
    (
        "company",
        "data/corpus/2026-08-17_2026.08.17-国信证券-张向伟-王新雨-公司研究-业绩点评-贵州茅台-600519-2026上半年收入同比增长1-3-继续深化市场化改革-bbba671e.pdf",
        "c195233b",  # i0a2-adjudicated: decision=admitted / material_type=research_report / scope=company
    ),
    (
        "macro",
        "data/corpus/2026-09-07_2026.09.07-国盛证券-宏观点评-这次不一样-3600亿增资银行保险的信号-08d04511.pdf",
        "1e021a8c",  # i0a2-adjudicated: decision=admitted / material_type=research_report / scope=macro
    ),
)


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation.clean import clean_reader_result
    from plugins.corpus.preparation.gaps import (
        blocking_gaps,
        gap_records,
        gap_summary,
    )
    from plugins.corpus.preparation.readers import read_document

    rows = []
    for domain, rel, expect_prefix in CANDIDATES:
        path = ROOT / rel
        if not path.is_file():
            rows.append({"domain": domain, "path": rel, "on_disk": False})
            continue
        source_id = hashlib.sha256(path.read_bytes()).hexdigest()
        result = read_document(path)
        clean = clean_reader_result(result)
        gap_keys = [region.key for region in clean.regions if region.ordinal is None]
        records = gap_records(gap_keys)
        summary = gap_summary(records)
        blocking = blocking_gaps(records)
        status_counts = Counter(region.status.value for region in clean.regions)
        rows.append(
            {
                "domain": domain,
                "path": rel,
                "on_disk": True,
                "source_id": source_id,
                "source_id_prefix": source_id[:8],
                "matches_expected_source_id": source_id.startswith(expect_prefix),
                "format": result.format.value if hasattr(result, "format") else None,
                "extractor_rev": result.extractor_rev,
                "unit_count": len(result.units),
                "region_status_counts": dict(status_counts),
                "gap_summary": summary,
                "blocking_gaps": [r.key for r in blocking],
                "publishable_local_precheck": not blocking,
            }
        )

    payload = {
        "artifact": "i3-1-append-candidates-preflight",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": (
            "本地只读：read_document + clean_reader_result + gaps 裁决（零 PG / 零模型 / 零网络；"
            "不写冻结件、不 replan PG）"
        ),
        "candidates": rows,
        "verdict": {
            "all_clean": all(r.get("publishable_local_precheck") for r in rows),
            "expected_counting_effect": (
                "company 1→2、macro 1→2（industry 已 2/3，不动）→ per_class_min_2 预期转 true"
            ),
        },
    }
    out = HERE / "i3-1-append-candidates-preflight.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                r["domain"]: {
                    "source_id_prefix": r.get("source_id_prefix"),
                    "matches_i0a2": r.get("matches_expected_source_id"),
                    "units": r.get("unit_count"),
                    "gap_summary": r.get("gap_summary"),
                    "blocking": r.get("blocking_gaps"),
                }
                for r in rows
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0 if payload["verdict"]["all_clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
