"""I3-2 共享文本工具（规则 ``evidence-mapping-5``）。

生成器 ``i3s2_evidence_targets.py``、自检 ``i3s2_verify_candidates.py``、
裁决应用器 ``i3s2_apply_decisions.py`` 共用同一套切分/匹配/词元规则——
避免"三处各写一套"导致批准投影与候选不一致。

纯标准库、无 I/O、无模型、无时钟。

主要概念：

- **段（segment）**：把 ``evidence_requirement`` 先按 ``，,；;。`` 切开。一段里"数值"与
  "限定条件"可以并存（复核 A4：旧版只在无强数值时才建定性要件，导致含数字子句里的
  限定被丢掉）。
- **数值要件**用字母边界匹配 ``(?<![\\dA-Za-z.])TOKEN(?![\\dA-Za-z.%])``，
  小数/百分数允许**数值等价**（``13.40`` ↔ 原文 ``13.4``）。
- **词元（content unit）**：ASCII/数字 token + 过滤后的 CJK 二元组，日期先掩码；
  用于"锚点覆盖了哪些词、还缺哪些词"（复核 A3：词面相近不得当成完整覆盖）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

FIELD_SEP = "\u0000"
PAGE_HINT = re.compile(r"第(\d+)页")
# 数值 token：前置不得是数字/字母/小数点（`R32` 的 32、`8230CF` 的 8230 不算命中）。
VALUE_TOKEN = re.compile(r"(?<![\dA-Za-z.])\d[\d,]*(?:\.\d+)?%?")
# 日期/期间：先掩码，不参与数值匹配（否则日期碎片会把整表数值变成强制目标）。
DATE = re.compile(
    r"\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?"
    r"|\d{4}\s*[-—~至]\s*\d{1,2}\s*月"
    r"|\d{1,2}\s*[-—~至]\s*\d{1,2}\s*月"
    r"|\d{4}\s*年(?:\s*\d{1,2}\s*月)?"
    r"|\d{1,2}\s*[-—~]\s*\d{1,2}\s*日?"
    r"|\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?"
    r"|\d{1,2}\s*季度?"
    r"|[一二三四]\s*季度"
    r"|\d{4}\s*[QH][1-4]"
)
NOTE_REF = re.compile(r"注\s*(\d+)")
WEAK_YEAR = re.compile(r"^(?:19|20)\d{2}$")
# 4 位数字后紧跟这些单位时是数值而非年份（"2030 元"是目标价，不是年份）。
PROMOTE_UNITS = ("元", "亿美元", "万元", "亿", "万", "点", "吨", "倍", "台", "人")
# 段切分：先按分号/句号切；**逗号只在"该子句既有数值又有标记"时**再切（由调用方决定），
# 避免把"约四个月""均下降"这类从属短语切成一堆无锚点的假缺口（复核 A4 + 二轮实测）。
SEGMENT_SPLIT = re.compile(r"[；;。\n]+")
# 答案侧/用法约束标记：表示"答案必须这样做"，不产生证据目标。
USAGE_MARKERS = (
    "不能混淆",
    "不得当作",
    "不能误记",
    "不得擅自",
    "不能代替",
    "不能解释为",
    "不能混用",
    "不等于",
    "不是",
    "保持",
    "区分",
    "标明",
    "标注",
    "注明",
    "所述",
    "解为",
    "记为",
    "视为",
)
# "事实性条件"标记：段里出现这些词说明还有需要取回原文的要件（优先给证据锚点而非仅记答案口径）。
EVIDENCE_MARKERS = ("条件", "样本", "口径", "限定", "预测", "注")
# 多来源题里"必须引用两份材料"这类要件由 source_coverage 规则承接。
SOURCE_REF_MARKERS = ("两份材料", "两个材料", "两份", "须引用", "必须引用")
# 含数值的段若出现这些标记，说明该段除数值外还有限定/口径要求，要另立定性要件。
VALUE_SEGMENT_MARKERS = USAGE_MARKERS + ("必须", "须", "需", "附条件", "样本", "口径", "限定")

KIND_PRIORITY = {
    "condition": 3,
    "rating": 3,
    "value": 2,
    "table_cell": 1,
}

_STOP_CHARS = set(
    "的了和与或为是不在等及以把将须必要对由得地中上下后前内外其本该这些我们你他也都就则即而且也但并"
    "从到向于被所之第余约左右并请可需要能会相"
)
_STOP_UNITS = {
    "报告",
    "材料",
    "数据",
    "说明",
    "给出",
    "必须",
    "需要",
    "要求",
    "表示",
    "显示",
    "认为",
    "指出",
    "以上",
    "以下",
    "其中",
    "包括",
    "分别",
    "期间",
    "两个",
    "两份",
    "四者",
    "不得",
    "不能",
    "不是",
    "注明",
    "标明",
    "属于",
    "份材",
    "引用",
    "取得",
    "材料",
    "口径",
}


def normalize(text: str) -> str:
    """归一化用于 token 匹配：全角空格/逗号/百分号统一、去千分位逗号、压缩空白。"""

    flat = text.replace("\u3000", " ").replace("，", ",").replace("％", "%")
    flat = re.sub(r"(?<=\d),(?=\d)", "", flat)
    return re.sub(r"\s+", "", flat)


def mask_dates(text: str) -> tuple[str, list[str]]:
    """掩码日期/期间表达式；返回 (掩码后文本, 期间 token 列表)。"""

    periods: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        periods.append(normalize(match.group(0)))
        return FIELD_SEP

    return DATE.sub(_replace, text), periods


def value_tokens(text: str) -> tuple[list[str], list[str]]:
    """(强数值 token **按出现顺序且不去重**, 弱 token 去重)。

    不去重是刻意的：requirement 里 ``0.0%`` 出现两次（价格分位、价差分位）就是两个要件，
    必须分别由两个不同单元格承载。
    """

    strong: list[str] = []
    weak: list[str] = []
    for match in VALUE_TOKEN.finditer(text):
        token = normalize(match.group(0))
        if not token:
            continue
        digits = token.rstrip("%").replace(".", "")
        tail = re.sub(r"\s+", "", text[match.end() : match.end() + 4])
        promoted = bool(WEAK_YEAR.match(digits)) and any(
            tail.startswith(unit) for unit in PROMOTE_UNITS
        )
        if not promoted and (WEAK_YEAR.match(digits) or len(digits) <= 1):
            if token not in weak:
                weak.append(token)
            continue
        strong.append(token)
    return strong, weak


def decimal_value(token: str) -> Decimal | None:
    raw = token.rstrip("%").replace(",", "")
    if not raw:
        return None
    try:
        return Decimal(raw).normalize()
    except InvalidOperation:
        return None


def is_decimal_like(token: str) -> bool:
    return "." in token or token.endswith("%")


def token_pattern(token: str) -> re.Pattern[str]:
    escaped = re.escape(token)
    return re.compile(rf"(?<![\dA-Za-z.]){escaped}(?![\dA-Za-z.%])")


def numeric_forms(text: str) -> dict[str, list[str]]:
    """文本里所有数值形态 → 该数值的原文写法（键为规范化十进制串）。"""

    table: dict[str, list[str]] = {}
    for match in VALUE_TOKEN.finditer(text):
        form = normalize(match.group(0))
        value = decimal_value(form)
        if value is None:
            continue
        table.setdefault(str(value), []).append(form)
    return table


def item_text(item: Mapping[str, object]) -> str:
    """item 可搜索文本：**逐字段**归一化后用不会出现的分隔符连接。

    直接拼接会把前一字段末字符与后一字段首字符粘成假边界（曾使 ``99.6%`` 因后面紧跟
    字母而漏掉精确匹配）。
    """

    keys = ("quote", "text", "cell", "row", "col", "unit", "period", "kind")
    return FIELD_SEP.join(normalize(str(item.get(key, ""))) for key in keys)


def match_token(token: str, text: str) -> list[str]:
    """返回该 token 在 item 文本上的命中写法；空列表 = 未命中。

    先边界精确匹配；小数/百分数若精确未中再做**数值等价**核对（原文写法不改写）。
    """

    if token_pattern(token).search(text):
        return [token]
    if not is_decimal_like(token):
        return []
    value = decimal_value(token)
    if value is None:
        return []
    return numeric_forms(text).get(str(value), [])


def segments_of(requirement: str) -> list[str]:
    """把 requirement 切成段（逗号/分号/句号）；空段丢弃，不猜补。"""

    return [part.strip() for part in SEGMENT_SPLIT.split(requirement) if part.strip()]


def content_units(text: str) -> set[str]:
    """内容词元：ASCII/数字 token + 过滤后的 CJK 二元组；日期先掩码。"""

    masked, _periods = mask_dates(text)
    flat = normalize(masked).lower()
    units: set[str] = set()
    for match in re.finditer(r"[a-z]{2,}|\d{2,}", flat):
        units.add(match.group())
    for run in re.findall(r"[\u4e00-\u9fff]+", flat):
        for index in range(len(run) - 1):
            bigram = run[index : index + 2]
            if bigram in _STOP_UNITS:
                continue
            if bigram[0] in _STOP_CHARS or bigram[1] in _STOP_CHARS:
                continue
            units.add(bigram)
    return units


def unit_stats(pool: Sequence[Mapping[str, object]], items_of) -> tuple[dict[str, float], dict[str, int], int]:
    """池内词元统计：返回 (IDF 权重, 文档频率, item 总数)。

    ``items_of(slot)`` 返回该槽位的 ``(index, item)`` 列表（由调用方提供，避免本模块依赖
    具体数据形状）。
    """

    frequency: dict[str, int] = {}
    total = 0
    for slot in pool:
        seen: set[str] = set()
        for _index, item in items_of(slot):
            total += 1
            seen |= content_units(item_text(item))
        for unit in seen:
            frequency[unit] = frequency.get(unit, 0) + 1
    return {unit: 1.0 / count for unit, count in frequency.items()}, frequency, total


def overlap(segment: str, item: Mapping[str, object], weights: Mapping[str, float]) -> tuple[int, float, float]:
    """(共有词元数, IDF 加权得分, 覆盖率)。"""

    segment_units = content_units(segment)
    if not segment_units:
        return 0, 0.0, 0.0
    shared = segment_units & content_units(item_text(item))
    score = sum(weights.get(unit, 1.0) for unit in shared)
    return len(shared), score, len(shared) / len(segment_units)


def _chars_in_order(unit: str, text: str) -> bool:
    """二元组的字是否**按序**都出现在文本里（去掉二元切分造成的假缺口，如"五主"⊂"五个主体"）。"""

    position = 0
    for char in unit:
        index = text.find(char, position)
        if index < 0:
            return False
        position = index + 1
    return True


def uncovered_terms(
    segment: str,
    item: Mapping[str, object],
    frequency: Mapping[str, int],
    total_items: int,
) -> list[str]:
    """段里未被该 item 覆盖的**判别性**词元（复核 A3：词面相近不等于完整覆盖）。

    两道过滤：① 文档频率不高于池内 item 数的 20%（至少 2），避免通用词被当成"漏掉的要件"；
    ② 二元组按字序包含即视为覆盖（同义切分/词序差异不算缺口）。真实缺口（如
    "四路径/化债/堵点/供应链消息"）不会被这两道滤掉。
    """

    text = item_text(item)
    missing = content_units(segment) - content_units(text)
    threshold = max(2, int(total_items * 0.2))
    return sorted(
        unit
        for unit in missing
        if frequency.get(unit, 0) <= threshold and not _chars_in_order(unit, text)
    )
