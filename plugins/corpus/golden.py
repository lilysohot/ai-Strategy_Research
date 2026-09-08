"""P0b B6：20 道黄金题（检索评测集）。

**为什么不按原配额编排**：原配额（A 行业×4 机构 / B 行业×3 机构 / 同系列 4 期 /
docx / 含表格 / 扫描页 / 故意重复）是按「A 股个股研报」设计的；实际语料是
**宏观 / 策略类为主**，个股研报仅贵州茅台 2 份。硬套配额只会造出题文不符的题，
验出来的分数没有意义。所以按**现有 17 份的实料**出题。

这份题集的第二个用途是**向量判据**（plan §6 B6 原文：「同时是向量判据输入」）：
先拿它测 FTS5 的 Recall，如果 Recall 已经够好，P1 就不必上 BGE-M3 + sqlite-vec；
不够好，缺口在哪一类题上一目了然。

判定方式刻意做成**确定性**的（检索是否命中预期文档），而不是「让 Agent 回答
再判对错」：后者每次跑结果都可能不同，无法作为回归基线，也无法定位是检索的
问题还是生成的问题。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from plugins.corpus.index import search

# 题目类型对应 plan §6：数字型 8 / 观点型 6 / 对比型 3 / 时效型 3
KIND_NUMBER = "数字"
KIND_OPINION = "观点"
KIND_COMPARE = "对比"
KIND_TIMELINESS = "时效"


@dataclass(frozen=True)
class Matcher:
    """预期命中的一份文档。

    用「标题片段 + doc_id 前缀（日期）」而不是 doc_id 本身来匹配：
    doc_id 含 content_hash，文件一改就变；标题片段 + 日期既稳定又可读。
    两份「全球流动性观察每周更新」标题完全相同，只能靠日期前缀区分——
    这正是时效型题目要考的点。
    """

    title_contains: str
    doc_prefix: str = ""


@dataclass(frozen=True)
class GoldenQuestion:
    qid: str
    question: str
    kind: str
    expects: tuple[Matcher, ...]
    # True = 所有 expects 都要被召回（对比型：跨文档的问题，少召回一份就算错）
    require_all: bool = False
    # 期望在原文里能看到的关键内容，供人工核对；不参与自动判定
    note: str = ""


def _m(title: str, prefix: str = "") -> Matcher:
    return Matcher(title_contains=title, doc_prefix=prefix)


GOLDEN_SET: tuple[GoldenQuestion, ...] = (
    # ── 数字型（8）────────────────────────────────────────────────────
    GoldenQuestion(
        "N1", "全球流动性最新估算规模是多少万亿美元", KIND_NUMBER,
        (_m("Capital-Wars_全球流动性观察每周更新", "2026-09-01"),),
        note="194.9 万亿美元",
    ),
    GoldenQuestion(
        "N2", "贵州茅台 2026 上半年收入同比增长百分之多少", KIND_NUMBER,
        (_m("国信证券", "2026-08-17"),),
        note="1.3%",
    ),
    GoldenQuestion(
        "N3", "全球流动性月度数据覆盖多少个国家", KIND_NUMBER,
        (_m("Capital-Wars_全球流动性观察每周更新", "2026-09-03"),),
        note="90 个国家",
    ),
    GoldenQuestion(
        "N4", "James Bulltard 买入 MDB 每周到期看涨价差的成本是多少美元", KIND_NUMBER,
        (_m("James-Bulltard_83126"),),
        note="6.44 美元",
    ),
    GoldenQuestion(
        "N5", "James Bulltard 卖出 EXE 股票的数量与获利", KIND_NUMBER,
        (_m("James-Bulltard_9226"),),
        note="卖出 15,000 股中的 10,000 股，获利 1.20 美元",
    ),
    GoldenQuestion(
        "N6", "仕佳光子投资决策报告的分析基准价是多少元", KIND_NUMBER,
        (_m("仕佳光子"),),
        note="157.93 元",
    ),
    GoldenQuestion(
        "N7", "油价突破到了多少美元", KIND_NUMBER,
        (_m("市场研判"),),
        note="90 → 92 美元",
    ),
    GoldenQuestion(
        "N8", "Simons 提到黄金近期尝试的高位与更高的高点分别是多少", KIND_NUMBER,
        (_m("黄金的多头与空头逻辑"),),
        note="4700 / 4772",
    ),
    # ── 观点型（6）────────────────────────────────────────────────────
    GoldenQuestion(
        "O1", "华创证券对贵州茅台给出什么投资评级", KIND_OPINION,
        (_m("华创证券", "2026-08-16"),),
        note="强推（维持）",
    ),
    GoldenQuestion(
        "O2", "国信证券对贵州茅台的投资评级是什么", KIND_OPINION,
        (_m("国信证券", "2026-08-17"),),
        note="优于大市",
    ),
    GoldenQuestion(
        "O3", "摩根大通对中国人工智能板块的态度与评级", KIND_OPINION,
        (_m("jpmorgan"),),
        note="维持增持 / 中性，上调智谱 MiniMax 目标价",
    ),
    GoldenQuestion(
        "O4", "Macro-Charts 认为哪些品种处于净多头极端", KIND_OPINION,
        (_m("Macro-Charts"),),
        note="工业金属（铜、铝）、玉米、汽油、标普500",
    ),
    GoldenQuestion(
        "O5", "仕佳光子覆盖机构的评级共识如何", KIND_OPINION,
        (_m("仕佳光子"),),
        note="7 家覆盖，买入/增持/推荐压倒性，中性 0、减持 0",
    ),
    GoldenQuestion(
        "O6", "Simons 对白银矿股的技术形态怎么看", KIND_OPINION,
        (_m("白银矿股"),),
        note="与 SILJ 表现高度相似，需关注图表四",
    ),
    # ── 对比型（3）：跨文档，少召回一份即算错 ─────────────────────────
    GoldenQuestion(
        "C1", "华创证券和国信证券分别对贵州茅台给出什么评级", KIND_COMPARE,
        (_m("华创证券", "2026-08-16"), _m("国信证券", "2026-08-17")),
        require_all=True,
        note="强推 vs 优于大市",
    ),
    GoldenQuestion(
        "C2", "资料库里关于油价突破与战争溢价有哪些材料", KIND_COMPARE,
        (_m("市场研判"), _m("小红书文案")),
        require_all=True,
        note="一份市场研判（md）+ 一份小红书文案（docx）",
    ),
    GoldenQuestion(
        "C3", "Simons-Substack 关于黄金和白银分别说了什么", KIND_COMPARE,
        (_m("黄金的多头与空头逻辑"), _m("白银矿股")),
        require_all=True,
        note="黄金多空逻辑 / 白银矿股图表四",
    ),
    # ── 时效型（3）：考的是「最新一期」能否被召回 ──────────────────────
    GoldenQuestion(
        "T1", "James Bulltard 最新一期的复盘是哪一期", KIND_TIMELINESS,
        (_m("James-Bulltard_9326", "2026-09-03"),),
        note="4 期中最晚的 09-03（09326 复盘）",
    ),
    GoldenQuestion(
        "T2", "全球流动性观察每周更新最新一期是哪天发布的", KIND_TIMELINESS,
        (_m("Capital-Wars_全球流动性观察每周更新", "2026-09-03"),),
        note="2 期中最晚的 09-03",
    ),
    GoldenQuestion(
        "T3", "Simons-Substack 最近一篇关于白银矿股的文章讲了什么", KIND_TIMELINESS,
        (_m("白银矿股", "2026-09-07"),),
        note="2026-09-07 白银矿股关注图表四",
    ),
)


@dataclass
class GoldenResult:
    """单题结果。"""

    question: GoldenQuestion
    hit: bool
    matched: tuple[str, ...] = ()
    missing: tuple[Matcher, ...] = ()


@dataclass
class GoldenReport:
    """整体报告。"""

    results: list[GoldenResult] = field(default_factory=list)
    top_k: int = 5

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for item in self.results if item.hit)

    @property
    def recall(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def by_kind(self) -> dict[str, tuple[int, int]]:
        """按题型统计 ``(通过, 总数)``——缺口定位到题型，才知道该补什么。"""
        stats: dict[str, tuple[int, int]] = {}
        for item in self.results:
            ok, total = stats.get(item.question.kind, (0, 0))
            stats[item.question.kind] = (ok + (1 if item.hit else 0), total + 1)
        return stats

    def failed(self) -> list[GoldenResult]:
        return [item for item in self.results if not item.hit]


def _matches(hit_doc_id: str, hit_title: str, matcher: Matcher) -> bool:
    if matcher.title_contains not in hit_title:
        return False
    return not matcher.doc_prefix or hit_doc_id.startswith(matcher.doc_prefix)


def run_golden(conn: sqlite3.Connection, *, top_k: int = 5) -> GoldenReport:
    """跑一遍黄金题集，返回逐题结果与 Recall。

    ``top_k=5`` 是默认而不是 1：Agent 的真实用法是「搜一次看前几条」，
    只要正确文档进了候选集就有机会被 fetch；卡在 top1 会低估实际可用性。
    """
    report = GoldenReport(top_k=top_k)
    for question in GOLDEN_SET:
        hits = search(conn, question.question, limit=top_k)
        matched: list[str] = []
        missing: list[Matcher] = []
        for matcher in question.expects:
            found = next(
                (hit for hit in hits if _matches(hit.doc_id, hit.title, matcher)),
                None,
            )
            if found is not None:
                matched.append(found.doc_id)
            else:
                missing.append(matcher)
        # require_all：跨文档题少一份即算错；否则命中任一份即算对
        ok = not missing if question.require_all else bool(matched)
        report.results.append(GoldenResult(
            question=question,
            hit=ok,
            matched=tuple(matched),
            missing=tuple(missing),
        ))
    return report


def format_golden_report(report: GoldenReport) -> str:
    """渲染成可对着逐题核对的文本。"""
    lines = [
        f"黄金题评测：{report.passed}/{report.total}  Recall@{report.top_k} = {report.recall * 100:.1f}%",
        "",
    ]
    for kind, (ok, total) in sorted(report.by_kind().items()):
        lines.append(f"  {kind}型  {ok}/{total}")
    failures = report.failed()
    if failures:
        lines.append("")
        lines.append("未命中：")
        for item in failures:
            lines.append(f"  [{item.question.qid}] {item.question.question}")
            lines.append("       期望：" + "；".join(
                m.title_contains + ("/" + m.doc_prefix if m.doc_prefix else "")
                for m in item.question.expects
            ))
    return "\n".join(lines)
