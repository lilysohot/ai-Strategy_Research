"""研报发布日期探查（契约 §4.3 唯一落点的原文依据重建）。

design-review 裁决：旧 ``documents.published`` 自 doc_id 日期前缀派生，语义废弃、
不迁移；新链只认**原文显式报告日期声明**（如「报告发布日期」「发布日期」「出具
日期」「落款日期」等字段），known 必带原文依据（``evidence_refs``，与准入探查
同一 ``feature=value[:locator]`` 记账风格），探查不到显式声明落 unknown。

R4 复核（2026-09-17）：文件名日期前缀与正文历史事件日期（成立日、财报截止日、
正文回顾）都**不是**报告发布日期——本探查只认显式声明字段；歧义（多日期/无
声明）落 unknown，不猜、不从句柄/路径推日期。人工纠正（human_review）留给
审核录入路径。
"""

from __future__ import annotations

import re
from datetime import date

from plugins.corpus.preparation.admission import ProbeInput
from plugins.corpus.preparation.contract import (
    PublicationDateOrigin,
    PublicationDatePrecision,
    PublicationDateStatus,
    ReportPublication,
)

#: 显式报告日期声明关键词（R4：区分「报告日期字段」与「事件日期」）。
#: 只有这些字段后的日期才构成发布依据；正文「公司于 2020 年成立」「财报截止
#: 2026/06/30」等历史/期间日期不参与。
_REPORT_DATE_LABEL = (
    r"(?:报告\s*发布日期|报告\s*日期|发布\s*日期|发表\s*日期|"
    r"出具\s*日期|落款\s*日期|报告\s*落款|签署\s*日期|编制\s*日期|报告\s*时间)"
)

#: 声明字段后的日期值：``2026/09/08`` / ``2026-09-08`` / ``2026年9月17日``
_REPORT_DATE_DECL_RE = re.compile(
    _REPORT_DATE_LABEL
    + r"\s*[:：]?\s*(20\d{2})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})\s*日?"
)

#: 扫描上限（与 probe_features 同纪律：head 400 / 行 200）
_HEAD_LIMIT = 400
_LINE_LIMIT = 200


def _as_date(y: str, m: str, d: str) -> date | None:
    """字符串转 date，非法日期（2026/13/45）返回 None 而不是抛错。"""
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def _known(value: date, evidence_ref: str) -> ReportPublication:
    return ReportPublication(
        value=value.isoformat(),
        precision=PublicationDatePrecision.DATE,
        status=PublicationDateStatus.KNOWN,
        evidence_refs=(evidence_ref,),
        origin=PublicationDateOrigin.SOURCE_EXPLICIT,
    )


def probe_report_publication(payload: ProbeInput) -> ReportPublication:
    """从原文探查研报发布日期：头部 → 正文行流，只取首个**显式声明**的报告日期。

    非法日期（2026/13/45）不算命中，继续向后找；全部落空显式返回 unknown。
    文件名标题（``payload.title``）不是原文依据，不参与日期判定（R4）。
    """
    for m in _REPORT_DATE_DECL_RE.finditer(payload.head_text[:_HEAD_LIMIT]):
        if d := _as_date(m.group(1), m.group(2), m.group(3)):
            return _known(d, f"report_date={d.isoformat()}:head[0:{_HEAD_LIMIT}]")

    for i, line in enumerate(payload.body_lines[:_LINE_LIMIT]):
        for m in _REPORT_DATE_DECL_RE.finditer(line):
            if d := _as_date(m.group(1), m.group(2), m.group(3)):
                return _known(d, f"report_date={d.isoformat()}:lines[{i}]")

    return ReportPublication(
        value=None,
        precision=PublicationDatePrecision.UNKNOWN,
        status=PublicationDateStatus.UNKNOWN,
    )
