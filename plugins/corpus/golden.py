"""P0b B6：20 道黄金题（检索评测集）。

**出题原则：按库里实际有什么出，而不是按预设配额出。**
原配额（A 行业×4 机构 / B 行业×3 机构 / 同系列 4 期 / docx / 含表格 / 扫描页 /
故意重复）是按「A 股个股研报」设计的；实际语料是**宏观 / 策略类为主**。
硬套配额只会造出题文不符的题，验出来的分数没有意义。

⚠️ **这份题集绑定语料样本，样本一换就必须重建。**
   每题 ``expects`` 指向具体的标题片段 + doc_id 日期前缀；样本被替换后这些锚点
   不再存在，Recall 必然掉到 0——那不是检索退化，是标尺失效。
   时效型尤其敏感：新增一期后「最新一期」的答案就变了
   （2026-09-09 重建时，James-Bulltard 最新由 9326 → **9826**，
   Capital-Wars 全球流动性最新由 09-03 → **09-08**）。

**重建记录**：

- 2026-09-08：语料 17 份，Recall@5 = 100%
- 2026-09-09：语料增至 **57 份**（新增大量券商周报），旧题集降到 **16/20**。
  其中 T1 / N1 属答案过期，N5 / N8 属同系列竞争加剧 ⇒ **按新语料重建本题集**。

这份题集的第二个用途是**向量判据**：先测 FTS 的 Recall，已经够好就不必上
向量；不够好，缺口在哪一类题上一目了然。

判定方式刻意做成**确定性**的（检索是否命中预期文档），而不是「让 Agent 回答
再判对错」：后者每次跑结果都可能不同，无法作为回归基线，也无法定位是检索的
问题还是生成的问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plugins.corpus.service import CorpusService

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
        "N1",
        "字节跳动获得的银团贷款规模是多少亿美元",
        KIND_NUMBER,
        (_m("字节获296亿美元银团贷款"),),
        note="296 亿美元（国金证券通信行业研究）",
    ),
    GoldenQuestion(
        "N2",
        "Figure 加码 Helix 算力投入了多少亿美元",
        KIND_NUMBER,
        (_m("figure斥35亿美元加码helix算力"),),
        note="35 亿美元（国泰海通机器人行业周报）",
    ),
    GoldenQuestion(
        "N3",
        "国盛证券提到增资银行保险的规模是多少亿",
        KIND_NUMBER,
        (_m("3600亿增资银行保险"),),
        note="3600 亿",
    ),
    GoldenQuestion(
        "N4",
        "华福证券基础化工周报提到电子特气涨幅超过多少",
        KIND_NUMBER,
        (_m("电子特气涨幅超24"),),
        note="涨幅超 24%",
    ),
    GoldenQuestion(
        "N5",
        "光大证券金属周报提到焦煤期货收盘价周内下跌多少",
        KIND_NUMBER,
        (_m("焦煤期货收盘价周内下跌3-64"),),
        note="3.64%",
    ),
    GoldenQuestion(
        "N6",
        "长江证券化工专题里小苏打出口占产量的比重是多少",
        KIND_NUMBER,
        (_m("长江证券-化工专题"),),
        note="30% 左右",
    ),
    GoldenQuestion(
        "N7",
        "贵州茅台 2026 上半年收入同比增长百分之多少",
        KIND_NUMBER,
        (_m("国信证券", "2026-08-17"),),
        note="1.3%",
    ),
    GoldenQuestion(
        "N8",
        "光力科技的主营业务和股票代码是什么",
        KIND_NUMBER,
        (_m("光力科技"),),
        note="300480，半导体划片机国内龙头",
    ),
    # ── 观点型（6）────────────────────────────────────────────────────
    GoldenQuestion(
        "O1",
        "华创证券对贵州茅台给出什么投资评级",
        KIND_OPINION,
        (_m("华创证券", "2026-08-16"),),
        note="强推（维持）",
    ),
    GoldenQuestion(
        "O2",
        "摩根大通对中国人工智能板块的态度与评级",
        KIND_OPINION,
        (_m("jpmorgan"),),
        note="维持增持 / 中性，上调智谱 MiniMax 目标价",
    ),
    GoldenQuestion(
        "O3",
        "国金证券怎么看 AI PCB 与半导体设备的布局时机",
        KIND_OPINION,
        (_m("ai-pcb及半导体设备迎来布局良机"),),
        note="迎来布局良机",
    ),
    GoldenQuestion(
        "O4",
        "华福证券为什么看好供给约束型周期品",
        KIND_OPINION,
        (_m("看好供给约束型周期品"),),
        note="美联储加息扩表可能性或已浮现",
    ),
    GoldenQuestion(
        "O5",
        "国金证券对钽价和锑价的判断是什么",
        KIND_OPINION,
        (_m("钽价有望启动上行"),),
        note="钽价有望启动上行、关注锑价止跌回升",
    ),
    GoldenQuestion(
        "O6",
        "华泰证券宏观海外周报如何看待联储加息",
        KIND_OPINION,
        (_m("联储加息悬念白热化"),),
        note="联储加息悬念白热化",
    ),
    # ── 对比型（3）：跨文档，少召回一份即算错 ─────────────────────────
    GoldenQuestion(
        "C1",
        "华创证券和国信证券分别对贵州茅台给出什么评级",
        KIND_COMPARE,
        (_m("华创证券", "2026-08-16"), _m("国信证券", "2026-08-17")),
        require_all=True,
        note="强推 vs 优于大市",
    ),
    GoldenQuestion(
        "C2",
        "国金证券和东吴证券分别对 GPT-6 Astra 发布有什么看法",
        KIND_COMPARE,
        (_m("gpt-6-astra-fable-5-1正式发布"), _m("gpt-6-astra发布")),
        require_all=True,
        note="国金：互联网行业研究；东吴：策略周评",
    ),
    GoldenQuestion(
        "C3",
        "光大证券和天风证券分别对 8 月美国非农数据给出了什么解读",
        KIND_COMPARE,
        (_m("2026年8月美国非农数据点评"), _m("非农大超预期")),
        require_all=True,
        note="光大：强非农降低加息门槛；天风：非农大超预期、加息预期升温",
    ),
    # ── 时效型（3）：考的是「最新一期」能否被召回 ──────────────────────
    GoldenQuestion(
        "T1",
        "James Bulltard 最新一期的复盘是哪一期",
        KIND_TIMELINESS,
        (_m("James-Bulltard_9826", "2026-09-08"),),
        note="5 期中最晚的 09-08（9826 复盘）",
    ),
    GoldenQuestion(
        "T2",
        "全球流动性观察最新一期是哪天发布的",
        KIND_TIMELINESS,
        (_m("全球流动性观察", "2026-09-08"),),
        note="3 期中最晚的 09-08（周度更新）",
    ),
    GoldenQuestion(
        "T3",
        "Simons-Substack 最近一篇讲了什么",
        KIND_TIMELINESS,
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


def run_golden(corpus: CorpusService, *, top_k: int = 5) -> GoldenReport:
    """跑一遍黄金题集，返回逐题结果与 Recall。

    ``corpus`` 是 ``CorpusService``：检索经它的 ``search``（PG + zhparser）。
    ``top_k=5`` 是默认而不是 1：Agent 的真实用法是「搜一次看前几条」，
    只要正确文档进了候选集就有机会被 fetch；卡在 top1 会低估实际可用性。
    """
    report = GoldenReport(top_k=top_k)
    for question in GOLDEN_SET:
        hits = corpus.search(question.question, limit=top_k)
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
        report.results.append(
            GoldenResult(
                question=question,
                hit=ok,
                matched=tuple(matched),
                missing=tuple(missing),
            )
        )
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
            lines.append(
                "       期望："
                + "；".join(
                    m.title_contains + ("/" + m.doc_prefix if m.doc_prefix else "")
                    for m in item.question.expects
                )
            )
    return "\n".join(lines)
