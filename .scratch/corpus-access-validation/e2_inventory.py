"""E2 · 研报池盘点：按内容哈希排除开发集来源，按机构/类型分类，产出覆盖矩阵。

零模型、只读（仅读 data/corpus 与开发集归档哈希清单）。产物写入本目录：
  e2-inventory.json   逐文件清单
  e2-coverage-matrix.md  机构 × 类型覆盖矩阵与留出集候选建议
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO / "data" / "corpus"
OUT_DIR = Path(__file__).resolve().parent

# 开发集 6 来源的内容 sha256 前 8 位（与 B0/B4 报告、gold jsonl source_id 一致）
DEV_SOURCES = {
    "6f14cc14": "company-001..008 贵州茅台（华创 2026-08-16）",
    "dddc7cd0": "company-004/005/006/008（2026-09-06）",
    "cc03f55b": "company-009..010",
    "793b3967": "macro-001..003（2026-09-06）",
    "174b6462": "industry-001 化工景气（长江 2026-08-13）",
    "f8e31696": "industry-002..003",
}

# 非券商研报（文件名来源字段），不进入留出集
NON_RESEARCH = ("James-Bulltard", "Capital-Wars", "Simons-Substack", "Macro-Charts", "FundaAI")

# 股票代码 6 位数字（整词）
TICKER = re.compile(r"(?<!\d)\d{6}(?!\d)")
# 行业/板块关键词（行业类研报信号）
INDUSTRY_KW = re.compile(
    r"行业(研究|周报|周观察|双周报|专题|数据)?|新材料|周期品|景气|"
    r"化工|金属|环保|机械|机器人|通信|传媒|医药|电子|互联网|有色|"
    r"电力设备|新能源|农业|地产|煤炭|焦煤|半导体|银行保险|药业|石油"
)
# 宏观/策略类研报信号
MACRO_KW = re.compile(
    r"策略周报|策略周评|策略定期|宏观|海外跟踪|海外周报|非农|数据面面观|"
    r"高频数据|流动性|独立行情|议息|增资|周观点|数据周报|市场回顾|盘面|复盘"
)
# 机构（官方名称结尾）
BROKER_SUFFIX = re.compile(r"(证券|国际|jpmorgan|高盛)$", re.IGNORECASE)
BROKER_PREFIX = ("国泰海通", "国联民生", "中银国际", "东吴", "平安", "光大", "兴业", "华泰",
                 "华源", "华福", "华创", "国信", "国投", "国盛", "天风", "长江", "中信建投", "中银", "高盛")


def _non_research_author(name: str) -> str | None:
    for token in NON_RESEARCH:
        if token in name:
            return token
    return None


def classify_type(name: str) -> str:
    if _non_research_author(name):
        return "non_research"
    # 公司：出现 6 位股票代码，或显式公司研究/业绩点评/IPO 专题
    if TICKER.search(name) or re.search(r"公司研究|业绩点评|ipo专题|中报点评", name):
        return "company"
    low = name.lower()
    # 行业：出现行业/板块关键词，且不同时是宏观/策略类
    if INDUSTRY_KW.search(low):
        return "industry"
    if MACRO_KW.search(low):
        return "macro"
    return "unclassified"


def parse_author(name: str) -> str:
    non_res = _non_research_author(name)
    if non_res:
        return non_res
    # 官方名称优先：token 以 "证券/国际/高盛" 结尾
    parts = name.split("-")
    for token in parts:
        if BROKER_SUFFIX.search(token):
            return token
    # 券商缩写前缀
    for prefix in BROKER_PREFIX:
        if prefix in name:
            return prefix
    return "unknown"

# 人工校核覆盖表（2026-09-29 首页文本实锤，键 = sha256 前 8 位）
MANUAL_OVERRIDES = {
    "1e021a8c": ("macro", "P1「证券研究报告|宏观研究·宏观点评」；「银行保险」系事件非行业归属"),
    "7d3ca3b9": ("industry", "P1「China Artificial Intelligence / Hong Kong Internet」多标的（Zhipu/MiniMax）调价，行业主题研究而非单公司"),
    "3738c927": ("company", "GS 茅台单标的评级研报（文件名）；P1/P2 图片型无文本层，若纳入按 protocol §1 记提取支持缺口"),
    "793b3967": ("macro", "P1 非农宏观点评；与开发集域标注 macro-001..003 一致"),
    "d01c64bf": ("macro", "P1「策略研究·策略定期报告」；「周期品」系观点非行业归属"),
    "f3b28791": ("macro", "P1「策略研究|A股市场策略」（张启尧团队），2026-09-29 用户确认归宏观"),
}


def _apply_overrides(entry: dict) -> None:
    ov = MANUAL_OVERRIDES.get(entry["sha256_8"])
    if ov:
        entry["report_type"], entry["review_note"] = ov


# 留出集排除记录（保留清单条目，退出候选池；protocol §1：缺口留数量与原因）
EXCLUDED_FROM_HOLDOUT = {
    "3738c927": "图片型 PDF（P1/P2 无文本层，pypdf 提取为空），2026-09-29 用户裁决剔除出留出集",
}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> None:
    entries = []
    for pdf in sorted(CORPUS_DIR.glob("*.pdf")):
        digest = sha256_of(pdf)
        short = digest[:8]
        author = parse_author(pdf.name)
        entries.append({
            "file": pdf.name,
            "sha256": digest,
            "sha256_8": short,
            "author": author,
            "report_type": "non_research" if author in NON_RESEARCH else classify_type(pdf.name),
            "is_dev_source": short in DEV_SOURCES,
        })
        _apply_overrides(entries[-1])
        ex = EXCLUDED_FROM_HOLDOUT.get(short)
        if ex:
            entries[-1]["excluded_from_holdout"] = ex

    dev_hits = {e["sha256_8"]: e["file"] for e in entries if e["is_dev_source"]}
    holdout = [
        e for e in entries
        if not e["is_dev_source"] and e["report_type"] != "non_research"
        and "excluded_from_holdout" not in e
    ]

    matrix: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in holdout:
        matrix[(e["author"], e["report_type"])].append(e["file"])

    lines = [
        "# E2 · 覆盖矩阵（初稿，机器生成）",
        "",
        f"- 语料池：{len(entries)} 个 PDF；开发集内容哈希命中：{len(dev_hits)}/6",
        f"- 留出候选（券商研报、非开发来源、未排除）：{len(holdout)} 篇",
        f"- 排除记录：{len(EXCLUDED_FROM_HOLDOUT)} 篇（" + "；".join(
            f"{k[:8]}：{v.split('，')[0]}" for k, v in EXCLUDED_FROM_HOLDOUT.items()) + "）",
        "",
        "| 机构 | company | industry | macro | unclassified |",
        "|---|---|---|---|---|",
    ]
    authors = sorted({a for a, _ in matrix})
    for author in authors:
        row = [author]
        for t in ("company", "industry", "macro", "unclassified"):
            files = matrix.get((author, t), [])
            row.append(str(len(files)) if files else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "## 采集起点建议（≥12 篇、≥3 机构、每版式 ≥2 份独立文档）",
        "",
        "1. 按矩阵优先选覆盖多类型的机构；同模板/同修订版/重复 PDF 按同组划分。",
        "2. `unclassified` 条目须人工归类后再纳入或排除。",
        "3. 开发集哈希未命中 6/6 时，先核对 data/corpus 是否被清理（归档副本在",
        "   `.scratch/b4.3-publish-20260929/archive/`）。",
    ]

    (OUT_DIR / "e2-inventory.json").write_text(
        json.dumps({"dev_hits": dev_hits, "entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT_DIR / "e2-coverage-matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"entries={len(entries)} dev_hits={len(dev_hits)} holdout_candidates={len(holdout)}")

if __name__ == "__main__":
    main()