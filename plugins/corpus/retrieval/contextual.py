"""Anthropic 式 Contextual Retrieval 的本地形态：片段说明只助检索，不是证据。

流程（与 Anthropic 原文一致，落到本项目的已发布原生投影上）：

    整篇文档 + 当前片段  →  模型生成该片段专属的简短说明  →  说明 + 原文片段
    →  同一文本建词法（PG ts_rank）与稠密向量索引  →  RRF 融合  →  原有选块/交付

三条硬边界，均在本模块内可离线校验：

1. 说明只由 `<document>` 原文派生，不引入文档中没有的数字与归属/预测措辞；
2. 说明与原文分存，检索输入身份（``index_text``）与原文身份（``chunk_text``）分开，
   取证与切片只认原文；
3. 说明不进入工具返回的证据文本，不能成为引文。
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from plugins.corpus.retrieval.embedding import text_hash

#: 说明口径版本：改动提示词、校验规则或拼接方式都要递增，否则旧说明不得复用。
PROMPT_VERSION = "contextual-note-v1"
#: 侧表与索引包里的上下文版本（与 PROMPT_VERSION 分开，便于同一提示词下重建）。
CONTEXT_VERSION = "chunk-note-1"
#: 单个说明的字符上限。Anthropic 建议 50–100 token，中文按 120 字约等。
NOTE_MAX_CHARS = 120
#: 太短的片段（页码「3/ 8」、图表轴数字残片、图表注记）本身不表意；给它们补说明
#: 会让这些碎片带上整篇文档的语义而被排到前面（2026-10-23 实测 p13 首位变成「3/ 8」）。
#: 这类片段只索引原文，不叠加说明。
FRAGMENT_MIN_CHARS = 12
#: 索引文本 = 说明 + 分隔符 + 原文片段；分隔符不参与原文切片。
INDEX_SEPARATOR = "\n"
_MARKERS = ("[原文片段]", "[来源元数据]")

SYSTEM_PROMPT = (
    "你是研报资料库的索引助手。你的输出只用于检索命中，不会被当作原文引用。"
    "只依据给定的 <document> 作答，不补充文档之外的背景、因果、归属或数字。"
    "只输出 JSON，不输出解释、前言或代码块标记。"
)

USER_TEMPLATE = """<document>
{document}
</document>

下面是该文档中的片段，每个片段带有 chunk_id。

{chunks}

请为每个片段写一条简短说明，说明它在整篇文档中的位置和讨论对象，用于提升检索命中。
每条说明要写清：讨论的公司／行业／产品／宏观对象、所属章节主题、时间或数据期、
以及计划／进行／已完成等状态（原文没写就不写）。

要求：
- 只使用 <document> 里出现的事实和措辞，不新增数字、年份、金额、机构或因果关系。
- 使用文档中的具体名词，不使用“本片段”“该文”“上述”等指代开头。
- 单行，不超过 {limit} 字，不加引号，不写评价（如“非常重要”“核心亮点”）。
- 只输出 {{"notes":[{{"chunk_id":"...","note":"..."}}]}}，不要输出其他字段。"""


class ContextNoteError(RuntimeError):
    """安全错误码：不携带原文、凭据或供应商响应体。"""

    def __init__(self, code: str, *, uncertain: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


def chunk_block(chunk_id: str, text: str) -> str:
    return f'<chunk id="{chunk_id}">\n{text}\n</chunk>'


def build_messages(document: str, chunks: Sequence[tuple[str, str]]) -> list[dict[str, str]]:
    """拼一次请求：整篇文档只出现一次，多个片段共享同一前缀。"""
    if not chunks:
        raise ContextNoteError("context_batch_empty")
    body = "\n\n".join(chunk_block(cid, text) for cid, text in chunks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(document=document, chunks=body, limit=NOTE_MAX_CHARS),
        },
    ]


def normalize_note(raw: str) -> str:
    """单行化：空白折叠、去包裹引号、去“上下文：”标签；不改动词句。"""
    if not isinstance(raw, str):
        raise ContextNoteError("note_not_text")
    text = " ".join(raw.split())
    if len(text) >= 2 and (text[0], text[-1]) in _QUOTE_PAIRS:
        text = text[1:-1].strip()
    text = re.sub(r"^(?:上下文|背景说明|说明)\s*[:：]\s*", "", text)
    return text


_QUOTE_PAIRS = frozenset(
    {('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』")}
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
#: 说明里若出现这些措辞，原文必须出现同一措辞，否则视为凭空归属、预测或完成状态。
_ATTRIBUTION = (
    "预计",
    "预测",
    "认为",
    "表示",
    "指出",
    "计划",
    "承诺",
    "宣布",
    "已经",
    "尚未",
    "同比",
    "环比",
    "目标",
)


def validate_note(note: str, document: str) -> None:
    """离线可判的四条：非空、长度、数字可回读、归属措辞可回读。"""
    if not note.strip():
        raise ContextNoteError("note_empty")
    if len(note) > NOTE_MAX_CHARS:
        raise ContextNoteError("note_too_long")
    if any(marker in note for marker in _MARKERS):
        raise ContextNoteError("note_marker_leak")
    source_numbers = set(_NUMBER.findall(document))
    invented = [value for value in _NUMBER.findall(note) if value not in source_numbers]
    if invented:
        raise ContextNoteError("note_number_not_in_source")
    missing = [word for word in _ATTRIBUTION if word in note and word not in document]
    if missing:
        raise ContextNoteError("note_attribution_not_in_source")


def parse_notes(raw: str, expected: Iterable[str]) -> dict[str, str]:
    """严格解析模型 JSON；缺项由调用方按 rejected 记账，不做静默补全。"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    try:
        payload = json.loads(text)
        items = payload["notes"]
        if not isinstance(items, list):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise ContextNoteError("note_response_invalid", uncertain=True) from None
    allowed = set(expected)
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ContextNoteError("note_response_invalid", uncertain=True)
        cid, note = item.get("chunk_id"), item.get("note")
        if not isinstance(cid, str) or cid not in allowed or not isinstance(note, str):
            continue
        result[cid] = normalize_note(note)
    return result


def index_text(note: str, chunk_text: str) -> str:
    """索引输入 = 说明 + 原文片段。原文必须整段保留在尾部，供切片映射校验。"""
    if not note.strip():
        raise ContextNoteError("note_empty")
    return f"{note}{INDEX_SEPARATOR}{chunk_text}"


def note_applies(chunk_text: str) -> bool:
    """片段是否值得叠加说明：过短的碎片只索引原文。"""
    return len(chunk_text.strip()) >= FRAGMENT_MIN_CHARS


def chunk_hash(chunk_text: str) -> str:
    return text_hash(chunk_text)


def input_hash(note: str, chunk_text: str) -> str:
    """说明或原文任一变化即产生新向量输入，旧向量不得冒充“已含上下文”。"""
    return text_hash(index_text(note, chunk_text))


def apply_notes(
    chunks: Sequence[dict[str, Any]], notes: dict[tuple[str, str], str]
) -> list[dict[str, Any]]:
    """给包内片段补 ``index_text`` 与新的 ``input_hash``；原文身份保持不变。"""
    result = []
    for chunk in chunks:
        key = (chunk["build_id"], chunk["chunk_id"])
        note = notes.get(key)
        if note is None:
            raise ContextNoteError("context_note_missing")
        text = chunk["search_text"]
        result.append(
            {
                **chunk,
                "note": note,
                "index_text": index_text(note, text),
                "input_hash": input_hash(note, text),
            }
        )
    return result


@dataclass(frozen=True)
class NoteConfig:
    """生成模型的独立配置；不复用聊天或 embedding 密钥。"""

    api_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    revision: str = ""
    timeout: float = 60.0
    max_document_chars: int = 120_000
    chunks_per_request: int = 6
    #: 推理型模型先把 token 花在 reasoning 上，content 为空即视为预算不足。
    max_output_tokens: int = 6000

    @classmethod
    def from_env(cls) -> NoteConfig:
        cfg = cls(
            api_url=os.getenv("CORPUS_CONTEXT_API_URL", "").strip(),
            api_key=os.getenv("CORPUS_CONTEXT_API_KEY", "").strip(),
            model=os.getenv("CORPUS_CONTEXT_MODEL", "").strip(),
            revision=os.getenv("CORPUS_CONTEXT_REVISION", "").strip(),
            timeout=float(os.getenv("CORPUS_CONTEXT_TIMEOUT_SECONDS", "60")),
            max_document_chars=int(os.getenv("CORPUS_CONTEXT_MAX_DOCUMENT_CHARS", "120000")),
            chunks_per_request=int(os.getenv("CORPUS_CONTEXT_CHUNKS_PER_REQUEST", "6")),
            max_output_tokens=int(os.getenv("CORPUS_CONTEXT_MAX_TOKENS", "6000")),
        )
        if not cfg.api_url or not cfg.model:
            raise ContextNoteError("context_model_not_configured")
        if not cfg.api_url.startswith("https://"):
            raise ContextNoteError("invalid_context_api_url")
        if not math.isfinite(cfg.timeout) or not 0 < cfg.timeout <= 300:
            raise ContextNoteError("invalid_context_timeout")
        if not 1 <= cfg.chunks_per_request <= 20:
            raise ContextNoteError("invalid_context_batch_size")
        if not 256 <= cfg.max_output_tokens <= 16000:
            raise ContextNoteError("invalid_context_max_tokens")
        return cfg

    @property
    def profile(self) -> str:
        """提示词版本 + 模型 + 批量口径决定说明缓存，不随密钥变化。"""
        return text_hash(
            json.dumps(
                {
                    "prompt_version": PROMPT_VERSION,
                    "api_url": self.api_url,
                    "model": self.model,
                    "revision": self.revision,
                },
                sort_keys=True,
            )
        )

    def endpoint(self) -> str:
        base = self.api_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"


@dataclass(frozen=True)
class NoteBatch:
    notes: dict[str, str]
    usage: dict[str, int]


class ChatNoteGenerator:
    """一次请求返回同文档多个片段的说明；失败不自动重试，避免重复计费。"""

    def __init__(self, config: NoteConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self.transport = transport

    def generate(self, document: str, chunks: Sequence[tuple[str, str]]) -> NoteBatch:
        cfg = self.config
        if not cfg.api_key:
            raise ContextNoteError("context_api_key_missing")
        if len(document) > cfg.max_document_chars:
            raise ContextNoteError("document_exceeds_character_guard")
        base = {
            "model": cfg.model,
            "temperature": 0,
            "max_tokens": cfg.max_output_tokens,
            "messages": build_messages(document, chunks),
        }
        # 少数供应商不接受 response_format / temperature：400 是确定性拒绝（未计费），
        # 去掉可选字段再发一次，不属于「重试未知结果」。
        attempts: list[dict[str, Any]] = [
            {**base, "response_format": {"type": "json_object"}},
            base,
            {key: value for key, value in base.items() if key != "temperature"},
        ]
        response = None
        for index, payload in enumerate(attempts):
            try:
                with httpx.Client(
                    timeout=cfg.timeout,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client:
                    current = client.post(
                        cfg.endpoint(),
                        headers={"Authorization": f"Bearer {cfg.api_key}"},
                        json=payload,
                    )
            except httpx.HTTPError:
                raise ContextNoteError(
                    "context_provider_transport_uncertain", uncertain=True
                ) from None
            if current.status_code == 200:
                response = current
                break
            if current.status_code != 400 or index == len(attempts) - 1:
                raise ContextNoteError(
                    f"context_provider_http_{current.status_code}",
                    uncertain=current.status_code >= 500,
                )
        assert response is not None
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            usage = {
                str(k): v
                for k, v in (body.get("usage") or {}).items()
                if isinstance(v, int) and not isinstance(v, bool) and v >= 0
            }
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ContextNoteError("context_response_uncertain", uncertain=True) from None
        if not content.strip():
            # 推理 token 吃满预算：已计费，不自动重发；调大 max_tokens 再跑。
            raise ContextNoteError("context_response_empty")
        notes = parse_notes(content, [cid for cid, _ in chunks])
        return NoteBatch(notes, usage)


def plan_batches(chunk_ids: Sequence[str], per_request: int) -> list[list[str]]:
    """按稳定顺序切批；顺序影响字节，所以固定按 chunk_id 排序。"""
    if per_request < 1:
        raise ContextNoteError("invalid_context_batch_size")
    ordered = sorted(chunk_ids)
    return [ordered[i : i + per_request] for i in range(0, len(ordered), per_request)]


def token_estimate(text: str) -> int:
    """粗估：中文约 1 字 1 token，ASCII 约 4 字符 1 token。只用于报价前的量级。"""
    ascii_chars = sum(1 for char in text if char.isascii())
    return ascii_chars // 4 + (len(text) - ascii_chars) + 1
