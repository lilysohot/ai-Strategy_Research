"""只读：对 3 项已提取未送达目标，检查 delivered 文本分词级匹配与 chunk 覆盖。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

WS = re.compile(r"[\s\u3000\xa0\u200b]+")


def norm(s):
    return WS.sub("", s or "")


# 目标 -> 引文所在 chunk 前缀（从 delivered_locators 推断 build_id 前缀）
CASES = {
    "c1ddcd8a-realestate": ("a6be5fb919b5ca0f", "地产竣工链条：钛白粉、玻璃价格处于低位水平。 本周钛白粉、玻璃的价格环比分别-0.36%、-0.97%，平板玻璃本周开工率 67.19%。"),
    "b7e932c8-index": ("5a213a956083ee64", "本周主要宽基指数普遍下跌 ，上证综指、东财全A分别下跌0.56%、1.20%，沪深300下跌1.33%；成长风格方面 ，创业板指下跌 4.03%，科创50下跌5.10%"),
    "b7e932c8-industry": ("5a213a956083ee64", "行业层面 ，本周申万 31个行业中 14个录得正收益 ，机构低配板块表现居前 ，传媒、银行和农林牧渔涨幅居前 ，分别上涨 6.0%、4.0%、3.3%；电子、有色金属和建筑材料表现较弱，分别下跌5.4%、5.0%、4.3%。"),
}

d = json.loads((HERE / "e6-data-delivery-holdout-rerun.json").read_text(encoding="utf-8"))
targets = {t["target_id"]: t for t in d["targets"]}


def main() -> int:
    import asyncio

    async def run():
        from plugins.tools.corpus_fetch import corpus_fetch

        for tid, (build_pre, quote) in CASES.items():
            t = targets[tid]
            print(f"\n===== {tid} =====")
            delivered_locators = t.get("delivered_locators") or []
            qn = norm(quote)
            print(f"  delivered_locators: {len(delivered_locators)} 个")
            # 逐个取回 chunk 文本，检查引文在哪个 chunk
            hit_chunks = []
            for loc in delivered_locators:
                if not loc.startswith(f"chunk:{build_pre}"):
                    continue
                raw = await corpus_fetch.func(
                    f"cv2:{build_pre}", locator=loc, view="full", max_chars=200000
                )
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                text = json.dumps(payload, ensure_ascii=False)
                tn = norm(text)
                if qn in tn:
                    hit_chunks.append((loc, "整条"))
                else:
                    toks = [norm(x) for x in quote.split() if len(norm(x)) >= 3][:5]
                    miss = [tok for tok in toks if tok not in tn]
                    if len(miss) < len(toks):
                        hit_chunks.append((loc, f"部分(缺{miss})"))
            print(f"  引文所在 chunk: {hit_chunks[:10]}")
            if not hit_chunks:
                print("  !! 所有 delivered chunk 均不含引文 —— 检索覆盖问题")
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
