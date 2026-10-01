"""验证 3 个 absent 目标的表格数据在源 PDF 文本中是否存在（只读，零模型）。

1) 在源 PDF 全文 get_text() 中搜索引文归一化子串；
2) 若命中，定位所在页并尝试 find_tables(lines/文本策略) 能否提取该表格；
3) 判断缺口归属：reader 可修复 vs 图片/不支持项。
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "e6-holdout-archive"

import fitz  # noqa: E402

CASES = [
    {
        "sample": "holdout-industry-003",
        "pdf": "c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885.pdf",
        "target": "c1ddcd8a-summarytable",
        "quote": "螺纹钢 元/吨 3240 0.9% 4.2% -2.4% -0.6% 6000",
    },
    {
        "sample": "holdout-macro-010",
        "pdf": "d179b615e82e4f6b47184ead5a34027abbd7bf2ef65ca4d599d03d31368c7595.pdf",
        "target": "d179b615-chart3",
        "quote": "涨跌幅:% 万得全A 南华商品 中证全债 上证 沪深300 创业板 工业品 金属 能化 农产品 被动补库 (1.83) (0.10) 0.29 (1.80) (2.21) (1.28) 0.21 0.29 0.14 (0.26)",
    },
    {
        "sample": "holdout-macro-012",
        "pdf": "f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279.pdf",
        "target": "f3b28791-table1",
        "quote": "板块 一级行业 二级行业 7 月以来 2026E 净利润上修幅度 2026 年预测净利润增速 7 月以来 涨跌幅 年初以来 涨跌幅 龙一 龙二 龙三 AI 算力硬件 电子 光学光电子 27.1% 194% -29.6% 6.9% 京东方A 惠科股份 TCL科技",
    },
]


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


def main() -> int:
    for case in CASES:
        pdf_path = next(ARCHIVE.rglob(case["pdf"]))
        q = norm(case["quote"])
        print(f"\n===== {case['sample']} :: {case['target']} =====")
        doc = fitz.open(pdf_path)
        hit_pages = []
        for pno in range(len(doc)):
            t = norm(doc[pno].get_text("text"))
            if q in t:
                hit_pages.append(pno + 1)
        print(f"  整条引文命中页: {hit_pages}")

        # 再按显著分词搜（表可能被切碎/跨行）
        tokens = [norm(x) for x in re.split(r"\s+", case["quote"]) if len(norm(x)) >= 3]
        # 取几个高区分度 token
        probe = ["螺纹钢", "3240", "万得全", "被动补库", "光学光电子", "27.1%", "京东方", "惠科"]
        for tok in probe:
            pages = [p + 1 for p in range(len(doc)) if norm(tok) in norm(doc[p].get_text("text"))]
            if pages:
                print(f"    token {tok!r} 命中页: {pages[:8]}")
        # 命中页上 try find_tables
        for p in hit_pages[:3]:
            page = doc[p - 1]
            for strategy in ("lines", "text", "lines_strict"):
                try:
                    ft = page.find_tables(strategy=strategy)
                    n = len(ft.tables)
                    first = ft.tables[0].extract()[0] if n else []
                    print(f"    page {p} strategy={strategy}: tables={n} first_row={first}")
                except Exception as exc:  # noqa: BLE001
                    print(f"    page {p} strategy={strategy}: ERR {exc}")
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
