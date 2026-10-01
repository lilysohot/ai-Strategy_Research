"""只读：直接调用 corpus_search 指向隔离库，查看 search_error 具体信息。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

import dotenv  # noqa: E402

dotenv.load_dotenv(ROOT / ".env")
os.environ["CORPUS_TARGET_DB"] = "e6_holdout_corpus"
os.environ.pop("PGOPTIONS", None)


async def main() -> int:
    from plugins.tools.corpus_search import corpus_search

    raw = await corpus_search.func("根据这篇贵州茅台研报，公司2026年上半年实现的总营收和归母净利润分别是多少，同比变化如何？", limit=10)
    import json

    print(json.dumps(raw, ensure_ascii=False, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
