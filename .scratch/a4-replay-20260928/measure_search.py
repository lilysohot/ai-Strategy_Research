"""量测 corpus_search(limit=10) 原始结果体积分布，用于给 D1 定一个有界预算。

零模型、PG 只读；只读问题文本，不看 gold。
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import dotenv_values  # noqa: E402

for _key, _value in dotenv_values(ROOT / ".env").items():
    if _key.startswith("CORPUS_") and _value is not None:
        os.environ.setdefault(_key, _value)
os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=30000"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from plugins.tools import get_builtin_tools  # noqa: E402

SCORING_INPUT = (
    ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
)


async def main() -> None:
    reg = get_builtin_tools()
    search = reg["corpus_search"]
    rows = [
        json.loads(line)
        for line in SCORING_INPUT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    raw_sizes: list[int] = []
    ctx_sizes: list[int] = []
    others: list[int] = []
    per_q: list[dict] = []
    for row in rows:
        raw = await search.ainvoke({"query": row["question"], "limit": 10})
        payload = json.loads(raw)
        hits = payload.get("hits") or []
        raw_sizes.append(len(raw))
        ctx = sum(len(json.dumps(h.get("context_locators") or [], ensure_ascii=False)) for h in hits)
        ctx_sizes.append(ctx)
        others.append(len(raw) - ctx)
        per_q.append(
            {
                "query_id": row["query_id"],
                "hits": len(hits),
                "raw": len(raw),
                "context_locators_chars": ctx,
                "other_chars": len(raw) - ctx,
            }
        )

    others.sort()
    print(
        json.dumps(
            {
                "questions": len(rows),
                "raw_max": max(raw_sizes),
                "raw_median": statistics.median(raw_sizes),
                "raw_p90": sorted(raw_sizes)[int(0.9 * len(raw_sizes))],
                "ctx_max": max(ctx_sizes),
                "other_max": max(others),
                "other_p90": others[int(0.9 * len(others))],
                "top10_raw": sorted(per_q, key=lambda r: -r["raw"])[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
