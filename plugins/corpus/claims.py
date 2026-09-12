"""D2：claim 抽取（LLM）——“市场一致预期”的地基。

为什么需要它（``ths-market-data.md``）：供应商**没有**一致预期 / 机构预测接口，
「市场一致预期」只能来自我们自己的 corpus 研报 ⇒ 必须把研报里的论断结构化出来。

设计要点：

1. **可溯源优先**：每条 claim 都带 ``doc_id`` + ``locator``（与 ``blocks`` 同一套
   取证句柄），claim 不是"模型总结"，而是能回到原文的那句话（硬闸①的口径）。
2. **先分级再调 LLM**（任务清单明确要求）：888 块全跑意义不大且费钱，先用规则
   筛掉「无数字 / 无预测词 / 纯免责声明」的块，只对候选块调 LLM。
3. **单块失败不中断**：LLM 返回乱码、超时、JSON 解析失败都只记一条 failure，
   绝不拖垮整批（与 ingest 同一条纪律）。
4. **块级台账（``claim_block_runs``）**：一块一行，记录"做过没有、成没成、用哪个
   模型/prompt 版本做的、花了多少 token"。跳过只认"同一模型 + 同一抽取器指纹"
   的成功记录 —— 换模型或改 prompt 会自动失效重抽，不会静默跳过。
   LLM 调用是**不可逆的花费**，所以落库粒度、跳过粒度都必须细到块（见
   ``CorpusService.extract_claims``）。

LLM 以**可调用对象注入**（``LlmFn``）：测试注入假实现，生产注入真实客户端，
本模块不绑定任何具体 SDK。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: ``kind`` 取值对齐 ``strategy_schema``：已发生的事实 vs 前瞻性表述
CLAIM_KINDS = ("fact", "forecast")

#: claim 文本上限：``UNIQUE (doc_id, seq, claim_text)`` 走 btree，
#: 过长文本会触发 PG 的索引行上限（约 2704 字节）⇒ 截断以保入库不失败。
MAX_CLAIM_CHARS = 500

LlmFn = Callable[[str], str]

CLAIMS_SQL = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id      BIGSERIAL PRIMARY KEY,
    doc_id        text        NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq           integer     NOT NULL,
    -- 取证句柄，与 blocks.locator 同一套：claim 必须能回到原文（硬闸①）
    locator       text        NOT NULL,
    claim_text    text        NOT NULL,
    kind          text        NOT NULL DEFAULT 'fact',
    -- 涉及标的代码（如 600519.SH），D3 挖掘 / D4 共识度按它聚合
    tickers       text[]      NOT NULL DEFAULT '{}',
    metric        text,
    value_text    text,
    -- 事实列 / 数值投影（d2-claims-design §5.1）：可枚举命名维度（地域/口径/三态）
    -- 编码进 metric，但这三列**必须落列**—— as_of 要做范围切片（as_of <= T），
    -- 编码进名字无法索引；value_num/unit 要做算术（均值/中位数/离散度），
    -- 名字里放不下。value_num/unit 由 Python 从 value_text 解析（零 LLM 成本），
    -- 解析失败时 value_num 留 NULL 并保留 value_text 原文，不得猜。
    value_num     numeric,
    unit          text,
    period        text,
    as_of         date,
    confidence    real,
    extracted_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_id, seq, claim_text)
);
CREATE INDEX IF NOT EXISTS idx_claims_doc     ON claims (doc_id, seq);
CREATE INDEX IF NOT EXISTS idx_claims_tickers ON claims USING gin (tickers);
CREATE INDEX IF NOT EXISTS idx_claims_kind    ON claims (kind);
-- 注意：as_of 的索引在 CLAIMS_MIGRATIONS_SQL 里建 —— 老库加列发生在迁移块，
-- 这里建了会让 CREATE INDEX 在老库上先于 ADD COLUMN 执行而直接失败。

-- 块级抽取台账：断点续跑的「跳过标记」，同时是每块的审计与花费记录。
-- 为什么必须有这张表：若只拿 ``claims`` 反推「这块做过没有」，就会漏掉
-- **抽出 0 条 claim 的块** —— 它们既没在 claims 里留痕，又每次重跑都被
-- 再调一次 LLM（同一块钱反复花，且永远跑不到尽头）。
CREATE TABLE IF NOT EXISTS claim_block_runs (
    doc_id      text        NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq         integer     NOT NULL,
    -- ok=抽取成功（claims_n 允许为 0，也算「做过」）；failed=调用失败，重跑会重试
    status      text        NOT NULL,
    claims_n    integer     NOT NULL DEFAULT 0,
    attempts    integer     NOT NULL DEFAULT 1,
    -- ★ 抽取来源指纹：跳过只认「同一模型 + 同一 prompt/解析器版本」的 ok 记录。
    -- 没有它，换模型（如 GLM-4.7 → GLM-4.5-AirX）或改 prompt 之后，旧块会被
    -- 静默永久跳过 —— 看起来在跑，实际一条都不抽，且不报错。
    model             text,
    extractor_version text,
    duration_ms       integer,
    -- 花费台账：有它才能回答「已经花了多少、剩下还要多少」
    prompt_tokens     integer,
    completion_tokens integer,
    error       text,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_claim_block_runs_status ON claim_block_runs (status);
CREATE INDEX IF NOT EXISTS idx_claim_block_runs_fingerprint
    ON claim_block_runs (status, model, extractor_version);
"""

#: 老库幂等迁移（与 ``init_db()`` 的 ``CREATE TABLE IF NOT EXISTS`` 同一条纪律）：
#: 三条事实列 + as_of 索引 + ``documents.doc_kind_override``（缺口#1 的误判纠正入口）。
#: **同时**删除 ``entities`` 死字段（缺口#4：全仓库无任何写入代码，留着只会让读者
#: 误以为已实现）。
CLAIMS_MIGRATIONS_SQL = """
ALTER TABLE claims ADD COLUMN IF NOT EXISTS value_num numeric;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS unit text;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS as_of date;
CREATE INDEX IF NOT EXISTS idx_claims_as_of ON claims (as_of);
ALTER TABLE claims DROP COLUMN IF EXISTS entities;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_kind_override text;
"""

CLAIMS_COMMENTS = (
    "COMMENT ON TABLE claims IS 'D2：从研报块抽取的结构化论断（可溯源到 locator）'",
    "COMMENT ON COLUMN claims.claim_id IS '旧版 claim 主键，自增，仅用于行级引用'",
    "COMMENT ON COLUMN claims.doc_id IS '来源文档 ID，外键指向 documents(doc_id)，删除文档时级联删除'",
    "COMMENT ON COLUMN claims.seq IS '来源 block 序号，与 blocks(doc_id, seq) 对应'",
    "COMMENT ON COLUMN claims.locator IS '取证句柄，与 blocks.locator 一致；claim 必须能回到原文'",
    "COMMENT ON COLUMN claims.claim_text IS 'LLM 抽出的旧版论断文本；v1 中同时承担断言和证据语义'",
    "COMMENT ON COLUMN claims.kind IS 'fact=已发生；forecast=前瞻性（目标价/预测，属 FORWARD_LOOKING）'",
    "COMMENT ON COLUMN claims.tickers IS '涉及标的代码数组，D3 挖掘与 D4 共识度按此聚合'",
    "COMMENT ON COLUMN claims.metric IS '旧版复合指标字段，可能同时编码主体、指标、口径和期间线索'",
    "COMMENT ON COLUMN claims.value_text IS '原文或模型输出中的数值文本，保留原始表达'",
    "COMMENT ON COLUMN claims.value_num IS "
    "'value_text 的数值投影（Python 解析，零 LLM 成本）；解析失败为 NULL，不得猜'",
    "COMMENT ON COLUMN claims.unit IS 'value_text 的单位（万元/亿元/%/万人…）；与 value_num 配套'",
    "COMMENT ON COLUMN claims.period IS '旧版期间原文/短文本；未拆分 period_end 和 period_grain'",
    "COMMENT ON COLUMN claims.as_of IS "
    "'发布/数据时点（D4 时效切片 as_of <= T 用）；模型给出，缺失时用 documents.published 兜底'",
    "COMMENT ON COLUMN claims.confidence IS '模型输出置信度；旧版仅作参考，不参与确定性质量裁决'",
    "COMMENT ON COLUMN claims.extracted_at IS 'claim 写入时间，默认 now()'",
    "COMMENT ON TABLE claim_block_runs IS "
    "'D2 块级抽取台账：断点续跑的跳过标记 + 每块审计/花费（模型、耗时、tokens、错误）'",
    "COMMENT ON COLUMN claim_block_runs.doc_id IS '来源文档 ID，外键指向 documents(doc_id)'",
    "COMMENT ON COLUMN claim_block_runs.seq IS '来源 block 序号；旧版台账按 doc_id + seq 唯一'",
    "COMMENT ON COLUMN claim_block_runs.status IS "
    "'ok=已成功抽取（claims_n 可能为 0，同样算「做过」）；failed=调用失败，重跑会重试'",
    "COMMENT ON COLUMN claim_block_runs.claims_n IS '该块本次成功写入的旧版 claim 数量，可为 0'",
    "COMMENT ON COLUMN claim_block_runs.attempts IS '该块累计被抽取次数（含历次重跑），达上限即视为死信'",
    "COMMENT ON COLUMN claim_block_runs.model IS "
    "'抽取时使用的模型名；跳过判断要带上它，换模型自动失效重抽'",
    "COMMENT ON COLUMN claim_block_runs.extractor_version IS "
    "'prompt + 解析器的内容指纹；改 prompt/解析器后自动失效重抽'",
    "COMMENT ON COLUMN claim_block_runs.duration_ms IS '该块抽取调用耗时，毫秒'",
    "COMMENT ON COLUMN claim_block_runs.prompt_tokens IS '该块抽取消耗的 prompt tokens；没有 usage 时为 NULL'",
    "COMMENT ON COLUMN claim_block_runs.completion_tokens IS "
    "'该块抽取消耗的 completion tokens；没有 usage 时为 NULL'",
    "COMMENT ON COLUMN claim_block_runs.error IS 'status=failed 时的异常摘要，便于批量重试前先看原因'",
    "COMMENT ON COLUMN claim_block_runs.updated_at IS '该块台账最后更新时间，upsert 时刷新'",
)


class BlockLike(Protocol):
    """只需 seq / locator / text 三个字段（``ingest.Block`` 天然满足）。

    Read-only by design: consumers only ever read these, and read-only is what
    lets a frozen dataclass (:class:`BlockView`) satisfy the protocol — a
    protocol with writable attributes cannot be implemented by one.
    """

    @property
    def seq(self) -> int: ...

    @property
    def locator(self) -> str: ...

    @property
    def text(self) -> str: ...


@dataclass(frozen=True)
class Claim:
    """一条结构化论断。

    ``value_num`` / ``unit`` / ``as_of`` 是 P1 新增的事实列（§5.1）：
    前两者由 Python 从 ``value_text`` 解析（零 LLM 成本），``as_of`` 优先取模型
    输出、缺失时由服务层用 ``documents.published`` 兜底。
    """

    doc_id: str
    seq: int
    locator: str
    claim_text: str
    kind: str = "fact"
    tickers: tuple[str, ...] = ()
    metric: str | None = None
    value_text: str | None = None
    value_num: Decimal | None = None
    unit: str | None = None
    period: str | None = None
    as_of: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class BlockView:
    """``blocks`` 表一行的轻量视图，满足 :class:`BlockLike`。"""

    seq: int
    locator: str
    text: str


@dataclass
class ExtractStats:
    """抽取统计（与 ``IngestStats`` 同风格：失败带原因）。"""

    documents: int = 0
    blocks: int = 0
    candidates: int = 0
    claims: int = 0
    skipped_no_signal: int = 0
    skipped_existing: int = 0  # 断点续跑：已抽取过的块，跳过以免重复花 LLM 调用
    skipped_dead_letter: int = 0  # 反复失败达上限的块：跳过，不再无限烧钱
    failed: int = 0
    review: int = 0
    rejected: int = 0
    truncated: int = 0
    stopped_early: bool = False  # 命中 should_stop（中断信号）后干净退出
    stopped_reason: str | None = None  # 提前退出的原因（中断 / 连续失败熔断）
    prompt_tokens: int = 0  # 本次已消耗的 prompt tokens（花费台账）
    completion_tokens: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        # Annotated: the literal otherwise narrows to dict[str, int] and the
        # failures list would not fit.
        data: dict[str, object] = {
            "documents": self.documents,
            "blocks": self.blocks,
            "candidates": self.candidates,
            "claims": self.claims,
            "skipped_no_signal": self.skipped_no_signal,
            "skipped_existing": self.skipped_existing,
            "skipped_dead_letter": self.skipped_dead_letter,
            "failed": self.failed,
            "review": self.review,
            "rejected": self.rejected,
            "truncated": self.truncated,
            "stopped_early": self.stopped_early,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }
        if self.stopped_reason:
            data["stopped_reason"] = self.stopped_reason
        if self.failures:
            data["failures"] = self.failures[:20]
        return data


# ── 分级（先规则筛，再决定是否值得花一次 LLM 调用） ──────────────────
# 有数字才可能有可验证的论断；有预测词才可能是 forecast。
_NUMERIC_RE = re.compile(r"\d")
_FORECAST_HINTS = (
    "预计",
    "预测",
    "预期",
    "目标价",
    "评级",
    "买入",
    "增持",
    "中性",
    "减持",
    "有望",
    "将达",
    "有望达",
    "同比",
    "环比",
    "增长",
    "增速",
    " forecast",
    "CAGR",
)
_NOISE_HINTS = (
    "免责声明",
    "未经",
    "书面许可",
    "分析师声明",
    "风险提示",
    "评级标准",
    "投资评级标准",
    "本报告由",
    "在法律许可",
    "版权归",
)


def is_noise(text: str) -> bool:
    """纯噪音块（免责 / 声明 / 评级标准说明）：永远不值得抽 claim。"""
    return any(hint in text for hint in _NOISE_HINTS)


def has_signal(text: str) -> bool:
    """是否值得调 LLM：**有数字** 且 **不是纯噪音**。"""
    if not text or not text.strip():
        return False
    if is_noise(text):
        return False
    return bool(_NUMERIC_RE.search(text))


def triage_blocks(blocks: Sequence[BlockLike]) -> tuple[list[BlockLike], int]:
    """分级：返回 ``(候选块, 被跳过的块数)``。"""
    candidates: list[BlockLike] = []
    skipped = 0
    for block in blocks:
        if has_signal(block.text):
            candidates.append(block)
        else:
            skipped += 1
    return candidates, skipped


# ── LLM 交互 ─────────────────────────────────────────────────────
#: 单块送入模型的最大字符数（超长表格块截断，避免单次调用过大）
PROMPT_MAX_CHARS = 2500

# ── prompt = 1 个骨架 + 3 份领域插槽（d2-claims-design §3.2） ────────
# 不做三套完整模板（会维护漂移：改一处忘两处）。差异全部收在插槽里，
# 骨架只放所有领域一致的契约。改任何一处都会改变 EXTRACTOR_VERSION →
# 自动失效重抽并按块整体替换。

#: **共享骨架**：claim 判定标准、输出契约、反编造纪律 —— 所有领域一致，不动。
PROMPT_SKELETON = """你是金融研报结构化抽取器。从下面这段研报原文中抽取**含具体数字或评级的陈述**。

什么算一条 claim（按此判断，不要过严）：
- 「2026 年上半年实现营业收入 1741 亿元，同比增长 1.3%」→ fact
- 「给予目标价 1888 元，维持"买入"评级」→ forecast
- 「PE(TTM) 为 19.8 倍」「市占率 25%」→ fact
不算：没有具体数字或评级的一般性描述（"公司竞争力突出"）、纯行业背景。

通用要求（所有文档领域一致；领域差异见下文规则）：
- 只输出 JSON 数组，不要任何解释文字、不要 Markdown 代码块。
- 每条包含：claim（论断原文或最接近的原文表述）、kind（fact=已发生的事实；forecast=预测/目标价/评级/市场预期）、
  tickers（涉及的代码，形如 600519.SH；没有则为 []）、metric（指标名，形态见下文领域规则）、
  value（数值原文，带单位）、period（报告期/数据期，如 2026H1、2026-08）、
  as_of（该数字的公布/数据时点，YYYY-MM-DD；原文明确写了日期才给，否则 null）、confidence（0-1）。
- 整段确实没有任何含数字/评级的陈述才输出 []。不要编造原文中不存在的数字。
"""

#: ``company`` 插槽：现有模板原样收编（这一路已工作正常，§6.2）。
COMPANY_SLOT = """本文档是**公司研报**：metric 直接用中文指标名（如 营业收入/归母净利润/EPS/毛利率/目标价/PE），不加任何前缀；tickers 填涉及的代码。

示例：
输入：公司 2026 年上半年实现营业收入 1741.44 亿元，同比增长 1.3%；给予目标价 1888 元，维持买入评级。
输出：[{"claim": "2026 年上半年实现营业收入 1741.44 亿元，同比增长 1.3%", "kind": "fact", "tickers": [], "metric": "营业收入", "value": "1741.44 亿元", "period": "2026H1", "as_of": null, "confidence": 0.9}, {"claim": "给予目标价 1888 元，维持买入评级", "kind": "forecast", "tickers": [], "metric": "目标价", "value": "1888 元", "period": null, "as_of": null, "confidence": 0.8}]
"""

#: ``industry`` 插槽（P2，§3.2/§5.3）：主体编码进 metric 前缀 ``<主体>.<指标>``，
#: **tickers 一律空**（§3.3 坐标模型：行业级数据不对应单一标的）。
INDUSTRY_SLOT = """本文档是**行业 / 板块 / 商品类**研报：主体是某个行业、板块或商品，不是个股。
metric 必须编码为 `<主体>.<指标>` 两段式（中文指标名）：

- 主体（第一段）：行业 / 板块用中文名（如 基础化工 / 电子 / 有色金属 / 医药生物 / 汽车 / 通信 / 计算机 / 机器人 / 锂电 / 农业），商品用品种名（如 焦煤期货 / 螺纹钢 / 白银 / 钛白粉 / PTA）。
  报告聚焦更细的子行业 / 品种时用子行业做主体（写 `钛白粉.价格`，不写 `基础化工.价格`）；
  主体在原文没有明确表述时**不要猜**，用原文最接近的行业表述。
- 指标（第二段，中文）：开工率 / 产能利用率 / 库存 / 价格 / 涨跌幅 / 产量 / 销量 / 排产 / 出货量 / 价差 / 需求 …
  词表没有的按同形态自拟（如 `基础化工.价差`、`机器人.产量`）。
- 同比 / 环比 / 百分点等口径**不编码**进 metric，保留在 value 与 claim 原文里；
  period 填数据所属期间（如 2026-08 / 2026H1 / 2016-2018），「本周」这类无编号周期留 null。
- **不需要三态拆分**：行业报告按原句抽取，不拆实际 / 预期 / 前值（那是宏观点评的结构）。
- **tickers 一律 []**：行业报告正文里的一串公司代码是样本 / 可比公司，不是本文档的标的；
  行业级数据不对应单一标的 —— 错误的坐标比缺失更危险。
- as_of：原文写明数据截止 / 公布日期才填（YYYY-MM-DD），否则 null。

示例：
输入：本周 PTA 开工率 82.3%，环比提升 1.2 个百分点；钛白粉价格 15800 元/吨，库存 12.6 万吨。焦煤期货主力合约收盘价 1280 元/吨，周内下跌 3.64%。我们预计 2026 年国内机器人出货量 35 万台。
输出：[{"claim": "PTA 开工率 82.3%，环比提升 1.2 个百分点", "kind": "fact", "tickers": [], "metric": "PTA.开工率", "value": "82.3%", "period": null, "as_of": null, "confidence": 0.9}, {"claim": "钛白粉价格 15800 元/吨", "kind": "fact", "tickers": [], "metric": "钛白粉.价格", "value": "15800 元/吨", "period": null, "as_of": null, "confidence": 0.9}, {"claim": "钛白粉库存 12.6 万吨", "kind": "fact", "tickers": [], "metric": "钛白粉.库存", "value": "12.6 万吨", "period": null, "as_of": null, "confidence": 0.9}, {"claim": "焦煤期货主力合约收盘价 1280 元/吨，周内下跌 3.64%", "kind": "fact", "tickers": [], "metric": "焦煤期货.价格", "value": "1280 元/吨", "period": null, "as_of": null, "confidence": 0.9}, {"claim": "我们预计 2026 年国内机器人出货量 35 万台", "kind": "forecast", "tickers": [], "metric": "机器人.出货量", "value": "35 万台", "period": "2026", "as_of": null, "confidence": 0.8}]
"""

#: ``macro`` 插槽：三态拆分（缺陷 1 的根治）+ 地域/口径编码（§3.2/§5.3/§6.1）。
#: 词表中英双语（缺口#2：18% 英文研报大多正是 macro 类；编码用英文反而有利）。
MACRO_SLOT = """本文档是**宏观 / 策略类**研报：主体是宏观指标或大类资产，不是个股。metric 必须编码为 `<地域>.<指标>[.<口径或三态>]`（地域在前）：

- 地域：US / CN / EU / JP / GLOBAL。地域未知时**不要猜**，metric 保留指标部分并在 claim 里保留原文表述。
- 口径（编码进 metric）：YoY（同比）/ MoM（环比）/ SAAR（季调折年）/ Cum（累计）。
- **三态判定**（宏观点评最常见的结构，每个数字都要判）：
  - 实际值（已公布的数据）→ 后缀 `.actual`，kind=fact；
  - 市场预期（"预期 X"、"一致预期"）→ 后缀 `.consensus`，kind=forecast；
  - 前值 → 后缀 `.previous`，kind=fact，且 period 用**前值所属期间**（8 月数据的前值 = 7 月）。
  「新增非农 16.2 万人，预期 5.6 万人，前值 2.1 万人」必须拆成 **3 条**，不得并作一条 ——
  actual 和 consensus 混在一起会让下游"一致预期"的结论直接反向。
- 资产价格/收益率/涨跌幅用自然后缀：`.yield`（收益率）/ `.return`（涨跌幅）/ `.price`（价格）。
- tickers 一律 []。
- as_of：宏观点评通常写明公布日期（如「9 月4 日公布」），必须解析为 YYYY-MM-DD 填入。

常用指标词表（中英对照；metric 用编码名，词表没有的指标按同形态自拟，地域必须正确）：
US.NFP 新增非农就业 · US.UNRATE 失业率 · US.AHE 平均时薪 · US.CPI / US.PPI ·
US.FFR 联邦基金利率 · US.UST10Y 10年期美债收益率 · US.SPX 标普500 · US.IA 初请失业金人数 ·
CN.CPI / CN.PPI · CN.TSF 社会融资规模 · CN.M2 · CN.NEWLOAN 新增人民币贷款 ·
CN.FAI 固定资产投资 · CN.IIP 工业增加值 · CN.RETAIL 社会消费品零售 · CN.PMI ·
CN.EXPORT / CN.IMPORT / CN.TRADEBAL 出口/进口/贸易差额 · CN.LPR / CN.MLF 利率 ·
GLOBAL.XAU 黄金 · GLOBAL.BRENT / GLOBAL.WTI 原油

示例：
输入：【1】新增非农就业16.2 万人，预期5.6 万人，前值由-2.3 万人修正为2.1 万人；【2】8 月失业率4.1%，预期4.1%，前值4.1%；【3】平均时薪同比升3.1%，预期升3.0%。10 年期美债收益率上行1bp 至4.78%。（2026 年9 月4 日公布）
输出：[{"claim": "新增非农就业16.2 万人", "kind": "fact", "tickers": [], "metric": "US.NFP.actual", "value": "16.2 万人", "period": "2026-08", "as_of": "2026-09-04", "confidence": 0.9}, {"claim": "预期5.6 万人", "kind": "forecast", "tickers": [], "metric": "US.NFP.consensus", "value": "5.6 万人", "period": "2026-08", "as_of": "2026-09-04", "confidence": 0.9}, {"claim": "前值修正为2.1 万人", "kind": "fact", "tickers": [], "metric": "US.NFP.previous", "value": "2.1 万人", "period": "2026-07", "as_of": "2026-09-04", "confidence": 0.9}, {"claim": "8 月失业率4.1%", "kind": "fact", "tickers": [], "metric": "US.UNRATE.actual", "value": "4.1%", "period": "2026-08", "as_of": "2026-09-04", "confidence": 0.9}, {"claim": "平均时薪同比升3.1%", "kind": "fact", "tickers": [], "metric": "US.AHE.YoY.actual", "value": "3.1%", "period": "2026-08", "as_of": "2026-09-04", "confidence": 0.9}, {"claim": "10 年期美债收益率上行1bp 至4.78%", "kind": "fact", "tickers": [], "metric": "US.UST10Y.yield", "value": "4.78%", "period": "2026-09-04", "as_of": "2026-09-04", "confidence": 0.9}]
"""

#: **表格追加段**（第 4 轴，§3.2）：块被 :func:`is_flat_table` 判定为
#: 「被压平的表格」时拼在领域插槽之后。不做成第 4 套模板 —— 它与三个插槽正交。
TABLE_APPENDIX = """**补充规则（本块是被压平的表格：行列关系被打散成了单元格流）**：
- 逐格抽取：每个 **行名 × 列头** 组合输出一条 claim，period 用该列的列头（如 2026E）。
- metric 必须带**子表前缀**：`<子表名>.<行名>`。子表名取「XX表（单位）」标题或图表标题
  （如 利润表 / 资产负债表 / 现金流量表 / 可比公司估值表）。
- value 直接取单元格数值（保留单位与括号负号）；claim 写「<子表名>.<行名> <列头> <值>」即可，
  不必成句，不要复述上下文。
- 行 / 列归属无法确定的单元格**不要抽**（错误的坐标比缺失更危险）；按表格出现顺序输出。
- 一行的数值个数与列头个数对不上（压平会丢列头）时：锚定不到列头的数值**不要抽**，
  严禁推测不存在的列头（如自己编 2029E）；宁缺勿错。
"""

_SLOT_BY_KIND: dict[str, str] = {
    "company": COMPANY_SLOT,
    "industry": INDUSTRY_SLOT,
    "macro": MACRO_SLOT,
}


# ── 表格块判据（缺口#3：§3.2 只说"被判定为被压平的表格"，这里给出可计算规则） ──
# 阈值用 2026-09-11 全库 928 块实测校准：64 个命中块逐一人工核对，绝大多数是
# 真实被压平的表格（财务三表 / 估值表 / 行业数据图表流）；目录页用点线占比排除。
# 已知残余误伤：机构通讯录、图表注释块 —— 它们本来就是表 / 单元格流，误伤代价
# 只是 prompt 多一段追加规则，不产生错误坐标；而漏判（表格当散文）会让模型重蹈
# 单块 20164 token 的覆辙，代价不对称，故阈值偏召回。
TABLE_MIN_LINES = 8
TABLE_MIN_DIGIT_RATIO = 0.10
TABLE_MAX_PUNCT_RATIO = 0.02
TABLE_MAX_AVG_LINE = 16
TABLE_MAX_LONG_LINE_FRAC = 0.05
TABLE_MAX_DOT_LINE_FRAC = 0.10

_CN_PUNCT = "，。；：、！？"
_DOT_LEADER_RE = re.compile(r"\.{6,}")


def is_flat_table(text: str) -> bool:
    """判定一块文字是不是「被压平的表格」（表格追加段的判据，缺口#3）。

    ingest 把表格压平成单元格流：行名与数值逐行排开，行列关系丢失。特征：

    - **数字占比高**（单元格一半以上是数字 / 百分号）；
    - **中文句读极少**（单元格流没有句子）；
    - **平均行长很短**（一行的长度 ≈ 一个单元格）；
    - **长行（>30 字符）占比极低**（表格里只有标题 / 资料来源是长行；散文
      大量长句 —— 这条挡住 PDF 碎片化的正文）；
    - **点线（目录引导符）占比低**（挡住目录页）。
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < TABLE_MIN_LINES:
        return False
    total = sum(len(ln) for ln in lines)
    if not total:
        return False
    digits = sum(ch.isdigit() for ln in lines for ch in ln)
    if digits / total < TABLE_MIN_DIGIT_RATIO:
        return False
    punct = sum(ch in _CN_PUNCT for ln in lines for ch in ln)
    if punct / total > TABLE_MAX_PUNCT_RATIO:
        return False
    if total / len(lines) > TABLE_MAX_AVG_LINE:
        return False
    long_lines = sum(len(ln) > 30 for ln in lines)
    if long_lines / len(lines) > TABLE_MAX_LONG_LINE_FRAC:
        return False
    dot_lines = sum(bool(_DOT_LEADER_RE.search(ln)) for ln in lines)
    return dot_lines / len(lines) <= TABLE_MAX_DOT_LINE_FRAC


def build_prompt(text: str, *, doc_kind: str = "company", max_chars: int = PROMPT_MAX_CHARS) -> str:
    """构造 prompt（骨架 + 领域插槽 + [表格追加段] + 截断后的原文）。

    用拼接与 ``max_chars`` 截断，不用 ``str.format``：模板里躺着 few-shot 的
    JSON 示例，``format`` 会把 ``{"claim": ...}`` 当占位符解析，直接 KeyError
    （实测踩过）。

    表格追加段按 :func:`is_flat_table` **自动判定**（调用方无需传标志），
    保证判据与 prompt 永远一致。
    """
    try:
        slot = _SLOT_BY_KIND[doc_kind]
    except KeyError:
        raise ValueError(f"未知 doc_kind：{doc_kind!r}（应为 {'/'.join(_SLOT_BY_KIND)}）") from None
    body = text if len(text) <= max_chars else text[:max_chars] + "\n…（截断）"
    appendix = TABLE_APPENDIX if is_flat_table(text) else ""
    return PROMPT_SKELETON + slot + appendix + "\n\n原文：\n" + body


#: 抽取口径的人工版本号 —— 改动 :func:`parse_claims_json` / :func:`claims_from_payload`
#: 这类"不进模板"的解析逻辑时加一。改 prompt 模板则指纹会自动变化，无需动它。
#: P1：解析口径新增 value_num/unit/as_of 派生 ⇒ 2。
#: P2：解析层强制坐标模型（industry/macro 的 tickers 清空，§3.3）⇒ 3。
#: P3：metric 别名归并（EPS→每股收益，§3.4）⇒ 4。
#: P4：parse_claims_json 增加截断 JSON 抢救（max_tokens 上限配套）⇒ 5。
_EXTRACTOR_REV = 5

#: 指纹输入 = prompt 全部组成部分 + 解析口径版本 + 截断长度（§3.2 指纹对接：
#: 骨架 / 插槽 / 表格段任何一处变化都自动失效重抽）。拆成元组是为了可测：
#: 测试断言表格段确实在指纹输入里。
_PROMPT_PARTS: tuple[str, ...] = (
    PROMPT_SKELETON,
    COMPANY_SLOT,
    INDUSTRY_SLOT,
    MACRO_SLOT,
    TABLE_APPENDIX,
)

#: 抽取器指纹。
#:
#: **为什么跳过判断必须带上它**：块一旦标记成 ``ok`` 就永不重抽，可"抽得好不好"
#: 完全取决于模型与 prompt。没有指纹时，换模型（GLM-4.7 → AirX）或改 prompt 之后
#: 旧块会被静默永久跳过 —— 看起来在跑，实际一条都不抽，而且不报错。
EXTRACTOR_VERSION = hashlib.sha256(
    f"{'|'.join(_PROMPT_PARTS)}|{_EXTRACTOR_REV}|{PROMPT_MAX_CHARS}".encode()
).hexdigest()[:12]


#: 注入式实现（测试 / 自定义 ``llm``）没有"配置模型"的概念，用这个稳定标识做
#: 指纹的一半：既让同一套假实现的重跑互相跳过，又不受环境里 ``OPENAI_MODEL`` 影响。
INJECTED_MODEL = "injected"


def configured_model() -> str:
    """当前配置的模型名 —— 跳过指纹的一半（与 :func:`build_default_llm` 同源）。"""
    return os.environ.get("OPENAI_MODEL") or "unknown"


#: 单块输出上限默认值（§10 Q5）：表格块逐格抽取天然长输出，实测无上限时
#: 单块吐过 20164 completion tokens。``CORPUS_LLM_MAX_TOKENS`` 可覆盖。
DEFAULT_MAX_OUTPUT_TOKENS = 4096


def max_output_tokens() -> int:
    """单块输出上限（token）：``CORPUS_LLM_MAX_TOKENS`` 覆盖，默认 4096。

    被截断的 JSON 数组由 :func:`parse_claims_json` 抢救已完整的前缀。
    """
    raw = os.environ.get("CORPUS_LLM_MAX_TOKENS", "").strip()
    if not raw:
        return DEFAULT_MAX_OUTPUT_TOKENS
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "CORPUS_LLM_MAX_TOKENS=%r 不是整数，回退默认 %d", raw, DEFAULT_MAX_OUTPUT_TOKENS
        )
        return DEFAULT_MAX_OUTPUT_TOKENS


#: ``max_tokens`` 是**思考 + 回答共享**的预算：deepseek-v4-flash 实测（2026-09-11）
#: 把 4096 全部烧在 reasoning 上（``finish_reason=length``、``content`` 为空），
#: 抢救出 0 条 claim。结构化抽取是机械任务，默认**关闭思考**让预算全给 JSON；
#: ``CORPUS_LLM_THINKING=enabled`` 显式打开（只在同时调大输出上限时有意义）。
_THINKING_DISABLED_BODY: dict[str, Any] = {"thinking": {"type": "disabled"}}


def thinking_extra_body() -> dict[str, Any]:
    """按 ``CORPUS_LLM_THINKING`` 返回请求附带的 ``thinking`` 参数。

    默认（未设置 / 非 ``enabled``）返回关闭思考的参数；设为 ``enabled`` 返回
    空字典（不附带，保持供应商默认行为）。端点不认识该参数时由
    :func:`build_default_llm` 降级重试。
    """
    if os.environ.get("CORPUS_LLM_THINKING", "").strip().lower() == "enabled":
        return {}
    return dict(_THINKING_DISABLED_BODY)


def _salvage_truncated_array(fragment: str) -> list[Any] | None:
    """从被输出上限截断的 JSON 数组里抢救**已完整**的对象前缀。

    ``max_tokens`` 截断的数组形如 ``[{...},{...},{"claim": "截`` —— 丢掉最后
    一个不完整对象，其余照常解析。**截断是设计内的行为**（§10 Q5 单块输出
    上限），抢救让"上限装不下的舍弃、装得下的不浪费"。
    """
    last = fragment.rfind("}")
    if last == -1:
        return None
    candidate = fragment[: last + 1].rstrip().rstrip(",") + "]"
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def parse_claims_json(raw: str) -> list[dict[str, Any]]:
    """容错解析 LLM 输出：**宁可返回空，也不抛异常**。

    LLM 常见脏输出：包 ```json 围栏、前后带解释、数组外面套对象；
    被 ``max_tokens`` 截断的数组走 :func:`_salvage_truncated_array` 抢救前缀。
    """
    if not raw or not raw.strip():
        return []
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        # 没有 "]" 可能是被截断的数组（截断点在 "}" 之后也在此分支）——先抢救
        if start != -1:
            salvaged = _salvage_truncated_array(cleaned[start:])
            if salvaged is not None:
                return [item for item in salvaged if isinstance(item, dict)]
        return []
    fragment = cleaned[start : end + 1]
    try:
        parsed = json.loads(fragment)
    except json.JSONDecodeError:
        salvaged = _salvage_truncated_array(fragment)
        if salvaged is None:
            logger.debug("claim JSON 解析失败，已跳过：%s", fragment[:120])
            return []
        parsed = salvaged
    if isinstance(parsed, dict):  # 有些模型会套一层 {"claims": [...]}
        for key in ("claims", "data", "items", "result"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_tickers(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _as_confidence(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, number))


# ── 事实列解析（d2-claims-design §5.1，零 LLM 成本的 Python 后处理） ──
#: 普通形态：``173,340 百万元`` / ``4.1%`` / ``-2.3 万人`` / ``+1bp`` / ``65.77 元``
_PLAIN_VALUE_RE = re.compile(r"^([+-]?\d[\d,]*(?:\.\d+)?)\s*(.*)$")
#: 会计负号形态：``(325)`` = -325（研报财务表惯用括号表负数）
_PAREN_VALUE_RE = re.compile(r"^\(([\d,]+(?:\.\d+)?)\)\s*(.*)$")


def parse_value(value_text: str | None) -> tuple[Decimal | None, str | None]:
    """把 ``value_text`` 拆成 ``(value_num, unit)``（§5.1）。

    实测样本：``"173,340 百万元"`` → ``(173340, "百万元")``；``"(325)"`` →
    ``(-325, None)``；``"4.1%"`` → ``(4.1, "%")``；``"65.77 元"`` → ``(65.77, "元")``。

    **解析失败返回 ``(None, None)`` 并保留 value_text 原文，不得猜** —— D4 要拿
    value_num 算均值 / 中位数 / 离散度，一个猜错的数比缺一个数危害大得多。
    用 :class:`Decimal` 而不是 float：PG ``numeric`` 列经 float 会有二进制误差，
    Decimal 从字符串原样构造，落库精确。
    """
    if not value_text:
        return None, None
    text = str(value_text).strip()
    negative = False
    if text.startswith("(") and text.endswith(")"):
        # 整体括号：会计负号。``(325) 百万元`` 这类"括号+单位"走下面正则的第二分支。
        stripped = text[1:-1].strip()
        match = _PAREN_VALUE_RE.match(f"({stripped})") or _PLAIN_VALUE_RE.match(stripped)
        if match:
            negative, text = True, stripped
    match = _PAREN_VALUE_RE.match(text) or _PLAIN_VALUE_RE.match(text)
    if match is None:
        return None, None
    digits = match.group(1).replace(",", "")
    try:
        number = Decimal(digits)
    except InvalidOperation:
        return None, None
    if negative or text.startswith("("):
        number = -number
    unit = match.group(2).strip() or None
    return number, unit


_AS_OF_RE = re.compile(r"^(?P<y>\d{4})[-/年](?P<m>\d{1,2})[-/月](?P<d>\d{1,2})日?$")


def parse_as_of(raw: Any) -> str | None:
    """解析 ``as_of`` 为 ISO ``YYYY-MM-DD``；不是明确的日期就返回 ``None``（不得猜）。

    接受 ``2026-09-04`` / ``2026/9/4`` / ``2026年9月4日``；模型被要求输出 ISO，
    但偶尔会跟着原文写中文日期，宽容解析比丢弃便宜。非真实日期（如 2026-02-30）
    返回 ``None``。
    """
    if raw is None:
        return None
    match = _AS_OF_RE.match(str(raw).strip())
    if match is None:
        return None
    year, month, day = (int(match.group(k)) for k in ("y", "m", "d"))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def apply_as_of_fallback(claims: Sequence[Claim], published: str | None) -> list[Claim]:
    """``as_of`` 为空时用 ``documents.published`` 兜底（§5.1，≈0 token 成本）。

    公司研报的报告日即发布日，近似成立；宏观 claim 的精确 as_of 由模型从原文
    （「9 月4 日公布」）给出，兜底只补洞。
    """
    iso = parse_as_of(published)
    if iso is None:
        return list(claims)
    return [claim if claim.as_of else replace(claim, as_of=iso) for claim in claims]


# ── 别名归并（§3.4）：落库前把别名映射到规范指标名 ────────────────
# 缺陷 3：同一份文档 EPS（3 条）与 每股收益（5 条）并存 ⇒ 按 metric 聚合
# "一致预期"只命中一半。表只收**确定同义**的对（宁缺勿错）：猜错的别名会把
# 两个不同指标混成一列，比重复计数更难清理；有把握的对随实测逐步补。
METRIC_ALIASES: dict[str, str] = {
    "eps": "每股收益",
    "每股盈利": "每股收益",
}


def normalize_metric(metric: str | None) -> str | None:
    """指标名归一（§3.4）：空白折叠后查别名表，未命中返回折叠原名。

    只做**整名**匹配，不动 ``主体.指标`` / ``地域.指标`` 的分段结构 ——
    industry / macro 的坐标编码（P1/P2）不能在这里被碰坏。大小写不敏感仅用于
    查表（``EPS`` / ``eps`` 同义），未命中的 metric 保留原大小写。
    """
    if not metric:
        return metric
    collapsed = " ".join(metric.split())
    return METRIC_ALIASES.get(collapsed.lower(), collapsed)


#: 单位 → （基准单位, 倍数）（§5.1 数值归一）：``1741 亿元`` = 1741 × 1e8 元。
#: ``value_num`` 保留**原文数值**（P1 口径，P1 验收记录的 16.2 万人不能变形），
#: 跨单位算术由聚合方（D4）乘倍数换算 —— 解析层改写数值会丢掉"原文写了什么"。
UNIT_SCALES: dict[str, tuple[str, Decimal]] = {
    "元": ("元", Decimal(1)),
    "万元": ("元", Decimal("1e4")),
    "百万元": ("元", Decimal("1e6")),
    "亿元": ("元", Decimal("1e8")),
}


def unit_scale(unit: str | None) -> tuple[Decimal, str]:
    """返回 ``(倍数, 基准单位)``；未知 / 空单位按 ``(1, 原样)`` 处理。

    用法：``base_value = value_num * unit_scale(unit)[0]`` —— 百万元与亿元口径
    的营收由此可加总（缺陷 9 的跨单位比较）。
    """
    if not unit:
        return Decimal(1), ""
    stripped = unit.strip()
    base, mult = UNIT_SCALES.get(stripped, (stripped, Decimal(1)))
    return mult, base


def claims_from_payload(
    payload: list[dict[str, Any]],
    *,
    doc_id: str,
    seq: int,
    locator: str,
) -> list[Claim]:
    """把 LLM 返回的结构化成 Claim（并做字段清洗与校验）。

    ``value_num`` / ``unit`` 由 :func:`parse_value` 从 ``value`` 原文派生（零 LLM
    成本，§5.1）；``as_of`` 经 :func:`parse_as_of` 校验，不合法就留空，由服务层
    用 ``documents.published`` 兜底；``metric`` 经 :func:`normalize_metric` 归并
    别名（§3.4 缺陷 3）。
    """
    claims: list[Claim] = []
    for item in payload:
        text = _as_str(item.get("claim")) or _as_str(item.get("claim_text"))
        if not text or len(text) < 4:
            continue
        text = text[:MAX_CLAIM_CHARS]
        kind = _as_str(item.get("kind")) or "fact"
        if kind not in CLAIM_KINDS:
            kind = "forecast" if any(h in text for h in _FORECAST_HINTS) else "fact"
        value_text = _as_str(item.get("value"))
        value_num, unit = parse_value(value_text)
        claims.append(
            Claim(
                doc_id=doc_id,
                seq=seq,
                locator=locator,
                claim_text=text,
                kind=kind,
                tickers=_as_tickers(item.get("tickers")),
                metric=normalize_metric(_as_str(item.get("metric"))),
                value_text=value_text,
                value_num=value_num,
                unit=unit,
                period=_as_str(item.get("period")),
                as_of=parse_as_of(item.get("as_of")),
                confidence=_as_confidence(item.get("confidence")),
            )
        )
    return claims


def extract_from_block(
    block: BlockLike,
    *,
    doc_id: str,
    llm: LlmFn,
    doc_kind: str = "company",
) -> list[Claim]:
    """对**单个块**调一次 LLM 并结构化。调用方负责捕获异常。

    ``doc_kind`` 决定用哪份领域插槽（§3.2）：company / industry / macro。

    **坐标模型在解析层强制**（§3.3）：industry / macro 的主体坐标编码进
    ``metric`` 前缀，``tickers`` 必须为空。插槽已在 prompt 里要求，但正文里
    一串公司代码对模型诱惑很大（化工专题正文 53 个代码）—— 这里兜底清空，
    否则一条越界的 tickers 就会让 D3/D4 按标的聚合时混入行业级数据。

    **表格块的 period 锚定护栏**（P4 实测教训）：压平的表格常出现一行 5 个
    数值对 3 个列头（ingest 丢了 2024A/2025A 头），模型会**编造** 2029E/2030E
    这类不存在的列头去凑数 —— prompt 禁不住（实测 18 条照编）。表格块里
    period 必须来自逐字出现的列头，锚定不到的整条丢弃：错误的坐标比缺失危险。
    散文块不适用（模型会把「2026 年上半年」规范化成 ``2026H1``，原文没有该字面）。
    """
    raw = llm(build_prompt(block.text, doc_kind=doc_kind))
    payload = parse_claims_json(raw)
    claims = claims_from_payload(payload, doc_id=doc_id, seq=block.seq, locator=block.locator)
    if doc_kind != "company" and any(c.tickers for c in claims):
        claims = [replace(c, tickers=()) for c in claims]
    if is_flat_table(block.text):
        claims = [c for c in claims if c.period is None or c.period in block.text]
    return claims


# ── 文档级标的兜底 ───────────────────────────────────────────────
# 为什么需要：模型在**表格块**里常常抽不出代码（表格里就没有代码列，
# 代码只写在标题/首块），实测一份贵州茅台研报 121 条 claim 的 tickers 全空 ——
# 而 D3 挖掘 / D4 共识度都是**按 ticker 聚合**的，空 ticker 等于这些数据白抽。
#
# 严格形态：``600519.SH`` / ``002694.SZ``（带交易所后缀，最可靠）。
# 裸代码：券商研报文件名常写成 ``...-贵州茅台-600519-...``（没有后缀）。
#: 用 ``(?![A-Za-z0-9])`` 而不是 ``(?!\w)``：``\w`` 是 Unicode 语义，中文紧跟其后
#: （如 ``600519.SH股票``）会把边界判错，反而漏掉真实代码。
_TICKER_STRICT_RE = re.compile(r"(?<!\d)(\d{6})\.(SH|SZ)(?![A-Za-z0-9])", re.IGNORECASE)
_TICKER_BARE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
#: 沪深号段 → 交易所。已知例外：指数代码（如上证指数 000001 会被判成 .SZ）。
_SH_PREFIXES = ("600", "601", "603", "605", "688", "689")
_SZ_PREFIXES = ("000", "001", "002", "003", "300", "301")


def _exchange_of(code: str) -> str | None:
    """按 6 位代码的号段推断交易所；号段不在表内则返回 ``None``（宁缺勿错）。"""
    if code.startswith(_SH_PREFIXES):
        return "SH"
    if code.startswith(_SZ_PREFIXES):
        return "SZ"
    return None


def document_ticker(title: str | None, block_texts: Sequence[str] = ()) -> str | None:
    """推断一份文档的标的，供 :func:`apply_doc_ticker` 兜底。

    查找顺序（从严到松）：

    1. **标题**里的严格形态 ``600519.SH``；
    2. **标题**里的裸代码（``...-贵州茅台-600519-...``），按号段推断交易所；
    3. **正文**里的严格形态，**仅当全文只出现唯一一个代码**。

    标题优先于正文：一份研报可能引用一堆公司代码（标题上的那个才是主角），
    实测同一份化工专题正文里出现 **53 个**代码、机器人行业周报 **46 个**。

    第 3 条的唯一性是关键判据：只出现一个代码说明"全文就在讲这一家公司"；
    出现多个说明这是行业 / 策略报告 —— 那时给整份文档硬塞一个"文档级标的"
    等于给它下面**所有** claim 打上错误坐标。**错误的坐标比缺失的坐标更危险**，
    因为下游无法察觉。所以宁可返回 ``None``（保持为空），也不猜。
    """
    cleaned_title = title or ""
    strict = _TICKER_STRICT_RE.search(cleaned_title)
    if strict:
        return f"{strict.group(1)}.{strict.group(2).upper()}"
    for bare in _TICKER_BARE_RE.finditer(cleaned_title):
        # 标题里可能先出现别的 6 位数字（年份等），号段不合法就继续往后找
        exchange = _exchange_of(bare.group(1))
        if exchange:
            return f"{bare.group(1)}.{exchange}"
    codes = {
        f"{match.group(1)}.{match.group(2).upper()}"
        for text in block_texts
        for match in _TICKER_STRICT_RE.finditer(text or "")
    }
    if len(codes) == 1:
        return next(iter(codes))
    return None


def apply_doc_ticker(claims: Sequence[Claim], ticker: str | None) -> list[Claim]:
    """给 ``tickers`` 为空的 claim 补上文档级标的。

    **模型给了就尊重模型的**（它看得到块内的代码列），只在它没给时兜底；
    没有可用的文档级标的时原样返回。
    """
    if not ticker:
        return list(claims)
    return [claim if claim.tickers else replace(claim, tickers=(ticker,)) for claim in claims]


# ── 文档领域分类（d2-claims-design §3.1，零 LLM 成本） ─────────────
#: ``doc_kind`` 决定抽取用哪套插槽（§3.2），是 claim 坐标系的第一轴。
DOC_KINDS = ("company", "industry", "macro")

#: 标题含这些词且全文无代码 ⇒ ``macro``（§3.1 第 3 行）。故意保守，只收
#: 纯宏观/策略词，不收指标/资产词 —— 「非农」「黄金」这类词行业报告也常用
#: （如「有色金属」「黄金珠宝」），扩词会误伤。误判由
#: ``documents.doc_kind_override`` 纠正（缺口#1 的入口，§3.1 列了但未展开）。
_MACRO_TITLE_HINTS = ("宏观", "策略", "周报", "流动性", "复盘", "联储", "美联储")


def classify_doc_kind(title: str | None, block_texts: Sequence[str] = ()) -> str:
    """零成本分类文档领域，规则与 :func:`document_ticker` 的三个分支同源（已实测零误标）。

    1. 标题含代码（严格形态或号段合法的裸代码），或**正文严格形态代码恰为 1 个**
       → ``company``（全文就在讲这一家公司）；
    2. 正文严格形态代码 **> 1 个** → ``industry``（行业 / 策略报告列举一堆公司）；
    3. 无任何代码 → 标题含「行业」⇒ ``industry``（「行业数据周报」这类标题
       也带「周报」宏观词，行业信号必须优先）；标题含宏观词 ⇒ ``macro``，
       否则 ``industry``。

    **副产品**：这套规则同时决定要不要给文档级标的兜底 —— ``industry`` / ``macro``
    **不给**（错误的坐标比缺失的坐标更危险，下游无法察觉），调用方必须按返回值
    门控 :func:`apply_doc_ticker`。
    """
    cleaned_title = title or ""
    if _TICKER_STRICT_RE.search(cleaned_title) or any(
        _exchange_of(m.group(1)) for m in _TICKER_BARE_RE.finditer(cleaned_title)
    ):
        return "company"
    codes = {
        f"{m.group(1)}.{m.group(2).upper()}"
        for text in block_texts
        for m in _TICKER_STRICT_RE.finditer(text or "")
    }
    if len(codes) == 1:
        return "company"
    if len(codes) > 1:
        return "industry"
    if "行业" in cleaned_title:
        return "industry"
    return "macro" if any(hint in cleaned_title for hint in _MACRO_TITLE_HINTS) else "industry"


def with_retry(
    llm: LlmFn,
    *,
    attempts: int = 3,
    base_delay: float = 1.5,
    sleep: Callable[[float], None] = time.sleep,
) -> LlmFn:
    """给 LLM 调用加退避重试：**限流 / 网络抖动不该让语料少一条 claim**。

    实测 GLM 侧会返回 429「模型访问量过大」，这类失败重试即可成功；
    而参数类 / 鉴权类错误重试无意义 —— 但区分成本高，这里统一重试后仍失败则抛，
    由 :meth:`extract_claims` 记成 failure（不中断整批）。
    """

    def _wrapped(prompt: str) -> str:
        last: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                return llm(prompt)
            except Exception as exc:  # 重试器需兜住所有异常
                last = exc
                if attempt == max(1, attempts) - 1:
                    raise
                sleep(base_delay * (2**attempt))
        assert last is not None
        raise last

    return _wrapped


def build_default_llm(usage_sink: dict[str, int] | None = None) -> LlmFn:
    """生产用 LLM：走 OpenAI 兼容接口（凭据来自 ``.env``）。

    这是**离线批处理**路径（不是 Agent 主链路），直接用 ``openai`` SDK；
    Agent 运行时的 LLM 仍走 ``frontier_agent.infra``。

    ``usage_sink`` 传入一个可变字典即累计 token 用量（键
    ``prompt_tokens`` / ``completion_tokens``），调用方按块取差值即可得到单块
    花费 —— 没有它就无法回答"已经花了多少、剩下还要多少"。

    两个超时/重试参数是**故意显式**的（默认值会把一次偶发挂起放大成十几分钟）：

    - ``timeout``（默认 300s，``CORPUS_LLM_TIMEOUT`` 可覆盖）：SDK 默认读超时
      600s，实测供应商会"TCP 连上了、请求发出去了，但一个字节都不回"，一次
      挂起就白等 10 分钟。观察到的最慢**合法**调用约 177s（长表格块吐几十条
      claim），故留 300s 余量。
    - ``max_retries=0``：重试策略只由 :func:`with_retry` 一处负责。若 SDK 自己
      再重试 2 次，会叠成「3 次 x 3 次」的请求放大 —— 限流时反而越重试越糟。
    - ``max_tokens``（单块输出上限，§10 Q5）：表格块逐格抽取天然是长输出，
      实测无上限时单块吐过 **20164** completion tokens。默认 4096
      （``CORPUS_LLM_MAX_TOKENS`` 可覆盖）；被截断的 JSON 数组由
      :func:`parse_claims_json` 抢救已完整的前缀，装得下的不浪费。
    - ``thinking=disabled``（默认）：``max_tokens`` 是思考与回答共享的预算，
      推理模型会把它全部烧在 reasoning 上、``content`` 为空（实测复现过）。
      结构化抽取默认关思考；``CORPUS_LLM_THINKING=enabled`` 打开。端点不认识
      该参数（如 OpenAI 官方）时记一次告警并**自动去掉参数重试**，之后不再附带。
    """
    from openai import BadRequestError, OpenAI

    base_url = os.environ.get("OPENAI_BASE_URL") or None
    api_key = os.environ.get("OPENAI_API_KEY") or ""
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未配置，无法执行 claim 抽取（D2）")

    timeout = float(os.environ.get("CORPUS_LLM_TIMEOUT", "300"))
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)

    thinking_supported = True  # 端点拒绝 thinking 参数后置 False，后续调用不再附带

    def _create(prompt: str, extra_body: dict[str, Any] | None) -> Any:
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是金融研报结构化抽取器，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=max_output_tokens(),
            extra_body=extra_body,
        )

    def _llm(prompt: str) -> str:
        nonlocal thinking_supported
        extra = thinking_extra_body() if thinking_supported else None
        try:
            response = _create(prompt, extra)
        except BadRequestError as exc:
            if extra and "thinking" in str(exc).lower():
                # 端点不认识 thinking（如 OpenAI 官方会 400）：降级为不带参数重试
                thinking_supported = False
                logger.warning("端点不认识 thinking 参数，本次起不再附带：%s", str(exc)[:120])
                response = _create(prompt, None)
            else:
                raise
        if usage_sink is not None:
            usage = getattr(response, "usage", None)
            if usage is not None:
                usage_sink["prompt_tokens"] = usage_sink.get("prompt_tokens", 0) + (
                    usage.prompt_tokens or 0
                )
                usage_sink["completion_tokens"] = usage_sink.get("completion_tokens", 0) + (
                    usage.completion_tokens or 0
                )
        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            logger.info(
                "单块输出达到 max_tokens=%d 被截断，JSON 前缀将按完整对象抢救", max_output_tokens()
            )
        return choice.message.content or ""

    return _llm
