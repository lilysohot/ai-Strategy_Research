"""D2：claim / entities 抽取（LLM）——“市场一致预期”的地基。

为什么需要它（``ths-market-data.md``）：供应商**没有**一致预期 / 机构预测接口，
「市场一致预期」只能来自我们自己的 corpus 研报 ⇒ 必须把研报里的论断结构化出来。

设计要点：

1. **可溯源优先**：每条 claim 都带 ``doc_id`` + ``locator``（与 ``blocks`` 同一套
   取证句柄），claim 不是"模型总结"，而是能回到原文的那句话（硬闸①的口径）。
2. **先分级再调 LLM**（任务清单明确要求）：888 块全跑意义不大且费钱，先用规则
   筛掉「无数字 / 无预测词 / 纯免责声明」的块，只对候选块调 LLM。
3. **单块失败不中断**：LLM 返回乱码、超时、JSON 解析失败都只记一条 failure，
   绝不拖垮整批（与 ingest 同一条纪律）。

LLM 以**可调用对象注入**（``LlmFn``）：测试注入假实现，生产注入真实客户端，
本模块不绑定任何具体 SDK。
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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
    period        text,
    confidence    real,
    entities      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    extracted_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_id, seq, claim_text)
);
CREATE INDEX IF NOT EXISTS idx_claims_doc     ON claims (doc_id, seq);
CREATE INDEX IF NOT EXISTS idx_claims_tickers ON claims USING gin (tickers);
CREATE INDEX IF NOT EXISTS idx_claims_kind    ON claims (kind);
"""

CLAIMS_COMMENTS = (
    "COMMENT ON TABLE claims IS 'D2：从研报块抽取的结构化论断（可溯源到 locator）'",
    "COMMENT ON COLUMN claims.locator IS '取证句柄，与 blocks.locator 一致；claim 必须能回到原文'",
    "COMMENT ON COLUMN claims.kind IS 'fact=已发生；forecast=前瞻性（目标价/预测，属 FORWARD_LOOKING）'",
    "COMMENT ON COLUMN claims.tickers IS '涉及标的代码数组，D3 挖掘与 D4 共识度按此聚合'",
)


class BlockLike(Protocol):
    """只需 seq / locator / text 三个字段（``ingest.Block`` 天然满足）。"""

    seq: int
    locator: str
    text: str


@dataclass(frozen=True)
class Claim:
    """一条结构化论断。"""

    doc_id: str
    seq: int
    locator: str
    claim_text: str
    kind: str = "fact"
    tickers: tuple[str, ...] = ()
    metric: str | None = None
    value_text: str | None = None
    period: str | None = None
    confidence: float | None = None
    entities: dict[str, Any] = field(default_factory=dict)


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
    failed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = {
            "documents": self.documents,
            "blocks": self.blocks,
            "candidates": self.candidates,
            "claims": self.claims,
            "skipped_no_signal": self.skipped_no_signal,
            "skipped_existing": self.skipped_existing,
            "failed": self.failed,
        }
        if self.failures:
            data["failures"] = self.failures[:20]
        return data


# ── 分级（先规则筛，再决定是否值得花一次 LLM 调用） ──────────────────
# 有数字才可能有可验证的论断；有预测词才可能是 forecast。
_NUMERIC_RE = re.compile(r"\d")
_FORECAST_HINTS = (
    "预计", "预测", "预期", "目标价", "评级", "买入", "增持", "中性", "减持",
    "有望", "将达", "有望达", "同比", "环比", "增长", "增速", " forecast", "CAGR",
)
_NOISE_HINTS = (
    "免责声明", "未经", "书面许可", "分析师声明", "风险提示", "评级标准",
    "投资评级标准", "本报告由", "在法律许可", "版权归",
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


def triage_blocks(blocks: list[BlockLike]) -> tuple[list[BlockLike], int]:
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
PROMPT_TEMPLATE = """你是金融研报结构化抽取器。从下面这段研报原文中抽取**含具体数字或评级的陈述**。

什么算一条 claim（按此判断，不要过严）：
- 「2026 年上半年实现营业收入 1741 亿元，同比增长 1.3%」→ fact
- 「给予目标价 1888 元，维持"买入"评级」→ forecast
- 「PE(TTM) 为 19.8 倍」「市占率 25%」→ fact
不算：没有具体数字或评级的一般性描述（"公司竞争力突出"）、纯行业背景。

要求：
- 只输出 JSON 数组，不要任何解释文字、不要 Markdown 代码块。
- 每条包含：claim（论断原文或最接近的原文表述）、kind（fact=已发生的事实；forecast=预测/目标价/评级）、
  tickers（涉及的代码，形如 600519.SH；没有则为 []）、metric（指标名，如 营业收入/净利润/PE）、
  value（数值原文，带单位）、period（报告期，如 2026H1）、confidence（0-1）。
- 整段确实没有任何含数字/评级的陈述才输出 []。不要编造原文中不存在的数字。

示例：
输入：公司 2026 年上半年实现营业收入 1741.44 亿元，同比增长 1.3%；给予目标价 1888 元，维持买入评级。
输出：[{"claim": "2026 年上半年实现营业收入 1741.44 亿元，同比增长 1.3%", "kind": "fact", "tickers": [], "metric": "营业收入", "value": "1741.44 亿元", "period": "2026H1", "confidence": 0.9}, {"claim": "给予目标价 1888 元，维持买入评级", "kind": "forecast", "tickers": [], "metric": "目标价", "value": "1888 元", "period": null, "confidence": 0.8}]

原文：
{text}
"""


def build_prompt(text: str, *, max_chars: int = 2500) -> str:
    """构造 prompt（截断超长块，避免单次调用过大）。

    用 ``replace`` 而不是 ``str.format``：模板里躺着 few-shot 的 JSON 示例，
    ``format`` 会把 ``{"claim": ...}`` 当占位符解析，直接 KeyError（实测踩过）。
    """
    body = text if len(text) <= max_chars else text[:max_chars] + "\n…（截断）"
    return PROMPT_TEMPLATE.replace("{text}", body)


def parse_claims_json(raw: str) -> list[dict[str, Any]]:
    """容错解析 LLM 输出：**宁可返回空，也不抛异常**。

    LLM 常见脏输出：包 ```json 围栏、前后带解释、数组外面套对象。
    """
    if not raw or not raw.strip():
        return []
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        return []
    fragment = cleaned[start : end + 1]
    try:
        parsed = json.loads(fragment)
    except json.JSONDecodeError:
        logger.debug("claim JSON 解析失败，已跳过：%s", fragment[:120])
        return []
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


def claims_from_payload(
    payload: list[dict[str, Any]],
    *,
    doc_id: str,
    seq: int,
    locator: str,
) -> list[Claim]:
    """把 LLM 返回的结构化成 Claim（并做字段清洗与校验）。"""
    claims: list[Claim] = []
    for item in payload:
        text = _as_str(item.get("claim")) or _as_str(item.get("claim_text"))
        if not text or len(text) < 4:
            continue
        text = text[:MAX_CLAIM_CHARS]
        kind = _as_str(item.get("kind")) or "fact"
        if kind not in CLAIM_KINDS:
            kind = "forecast" if any(h in text for h in _FORECAST_HINTS) else "fact"
        claims.append(
            Claim(
                doc_id=doc_id,
                seq=seq,
                locator=locator,
                claim_text=text,
                kind=kind,
                tickers=_as_tickers(item.get("tickers")),
                metric=_as_str(item.get("metric")),
                value_text=_as_str(item.get("value")),
                period=_as_str(item.get("period")),
                confidence=_as_confidence(item.get("confidence")),
            )
        )
    return claims


def extract_from_block(
    block: BlockLike,
    *,
    doc_id: str,
    llm: LlmFn,
) -> list[Claim]:
    """对**单个块**调一次 LLM 并结构化。调用方负责捕获异常。"""
    raw = llm(build_prompt(block.text))
    payload = parse_claims_json(raw)
    return claims_from_payload(payload, doc_id=doc_id, seq=block.seq, locator=block.locator)


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


def build_default_llm() -> LlmFn:
    """生产用 LLM：走 OpenAI 兼容接口（凭据来自 ``.env``）。

    这是**离线批处理**路径（不是 Agent 主链路），直接用 ``openai`` SDK；
    Agent 运行时的 LLM 仍走 ``frontier_agent.infra``。
    """
    import os

    from openai import OpenAI

    base_url = os.environ.get("OPENAI_BASE_URL") or None
    api_key = os.environ.get("OPENAI_API_KEY") or ""
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未配置，无法执行 claim 抽取（D2）")

    client = OpenAI(api_key=api_key, base_url=base_url)

    def _llm(prompt: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是金融研报结构化抽取器，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    return _llm
