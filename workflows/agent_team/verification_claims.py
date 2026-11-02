"""Narrow, auditable detection of report-wide verification assurances.

This is a language-pattern guard, not a fact checker. It must not treat domain
words (e.g. 整体目标), reviewer titles, estimates or opinions as assurances.
"""

from __future__ import annotations

import re
from typing import Any

_VERIFY = r"(?:核验|验证|核对|复核)(?!员|人员|任务)"
_OBJECT = r"(?:原文)?(?:数字|数值|数据|引文|引用|事实|结论|结果|观点|内容|断言|证据|检查项)?"
_DONE = r"(?:均已|已经|已|均|都已|都)(?:完成|通过)?"
_SUCCESS = r"(?:通过|完成|完毕|无误)"
_REPORT = r"(?:全文|整份(?:报告|文档|研报)|本(?:报告|答复|文))"
_BLANKET_VERIFICATION = re.compile(
    r"已获充分交叉验证"
    rf"|(?:全部|所有){_OBJECT}{_DONE}{_VERIFY}{_SUCCESS}?"
    rf"|(?:全部|所有){_OBJECT}{_VERIFY}{_SUCCESS}"
    rf"|(?:已完成|完成了)(?:全部|所有|全面){_OBJECT}{_VERIFY}"
    rf"|(?:全面|整体){_VERIFY}{_SUCCESS}"
    rf"|{_REPORT}(?:\s|\*){{0,4}}(?:{_DONE}|完成|通过|经过)"
    rf"(?:了|逐字|\s|\*){{0,4}}{_VERIFY}{_SUCCESS}?"
    rf"|{_REPORT}{_VERIFY}(?:已)?{_SUCCESS}"
    r"|^\s*(?:fully|thoroughly|exhaustively)\s+(?:cross[- ]?)?verified\b"
    r"|(?:the\s+)?(?:entire|full|whole)\s+(?:document|report|paper)\s+"
    r"(?:has been|is|was)\s+(?:fully\s+)?verified\b"
    r"|\b(?:all|every)\s+(?:findings?|claims?|figures?|results?)\s+"
    r"(?:have been |are )?verified\b",
    re.IGNORECASE,
)
_FINAL_QUOTES = re.compile(
    r"(?:本答复|本报告|最终报告|最终答复)(?:中|的|内|\s|\*){0,4}"
    r"(?:所有|全部)(?:原文)?(?:引文|引用).{0,12}"
    r"(?:核验员|核验人员).{0,16}(?:回查|核对|核验|验证)",
)
_SENTENCE = re.compile(r"[^\n]+?(?:[。！？]|[.!?](?=\s|$)|(?=\n|$))")
_SCOPED = re.compile(
    r"(?:已声明|列明|上述)(?:的)?(?:检查|核验项)|\b(?:declared|listed) checks?\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"(?:尚未|未|不能|无法|并非|不应|不要)[^，,；;但。]{0,6}$"
    r"|\b(?:not|cannot|can't)(?:\s+\w+){0,2}\s*$",
    re.IGNORECASE,
)
_NON_SUCCESS = re.compile(r"\s*(?:失败|未通过|不通过|尚未|未完成|为错误)")


def verification_claim_findings(text: str) -> list[dict[str, Any]]:
    """Return exact source spans; no assertion of a factual contradiction."""
    findings = []
    for sentence_match in _SENTENCE.finditer(text):
        sentence = sentence_match.group()
        for rule, pattern in (
            ("blanket_verification", _BLANKET_VERIFICATION),
            ("final_report_verification_scope", _FINAL_QUOTES),
        ):
            for match in pattern.finditer(sentence):
                nearby = sentence[max(0, match.start() - 24) : match.end() + 24]
                prefix = sentence[max(0, match.start() - 24) : match.start()]
                if (
                    _SCOPED.search(nearby)
                    or _NEGATION.search(prefix)
                    or _NON_SUCCESS.match(sentence[match.end() :])
                ):
                    continue
                findings.append(
                    {
                        "rule": rule,
                        "reason": "Declared checks cover only their bound subjects and criteria; "
                        "they do not certify this report-wide assurance.",
                        "match": match.group(),
                        "sentence": sentence,
                        "start": sentence_match.start(),
                        "end": sentence_match.end(),
                        "match_start": sentence_match.start() + match.start(),
                        "match_end": sentence_match.start() + match.end(),
                    }
                )
    return findings


def omit_verification_assurances(text: str, findings: list[dict[str, Any]]) -> str:
    """Omit affected sentences, preserving all other prose and inference labels.

    Do not silently rewrite a verdict as a fact. The caller discloses omissions
    and retains the exact original candidate and spans in the publication audit.
    """
    for start, end in sorted({(f["start"], f["end"]) for f in findings}, reverse=True):
        text = text[:start] + text[end:]
    return text.strip()
