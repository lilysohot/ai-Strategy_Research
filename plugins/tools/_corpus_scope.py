"""Preserve retrieval limits and reject narrow, explicit claims of exhaustive coverage.

This detects scope overstatement, not the truth or relevance of individual facts.
"""

from __future__ import annotations

import re
from typing import Any

_SENTENCE = re.compile(r"[^\n]+?(?:[。！？]|[.!?](?=\s|$)|(?=\n|$))")
_ABSOLUTE = re.compile(
    r"(?:全库|整个(?:资料库|语料库)|库内|资料库(?:中|里|内)?|语料库(?:中|里|内)?)"
    r"(?:[\s*`]|完全|确实|确为|的|是|范围内){0,12}"
    r"(?:没有|不存在|无(?!法)|未见|未发现|零覆盖|仅有|只有|最新)"
    r"|(?:资料库|语料库)[^。！？\n]{0,30}?(?:零覆盖|全部文档均已|全部来源均已)"
    r"|(?:全库|库内)(?:最晚|最新)(?:的)?(?:版本|模型|发布|记录)"
    r"|(?:资料库|语料库)(?:记载|记录|显示)(?:的|，|,)?[^。！？\n]{0,24}?"
    r"(?:当前|目前)?最新[^。！？\n]{0,20}?(?:模型|版本|发布|记录)"
    r"|\b(?:no|only)\b[^.!?\n]{0,60}\b(?:entire|whole) (?:corpus|library)\b"
    r"|\b(?:latest|newest)\b[^.!?\n]{0,50}\bin the (?:corpus|library)\b",
    re.IGNORECASE,
)
_QUALIFIED = re.compile(
    r"(?:不能|无法|不应|不要|不代表|不等于|并非)(?:据此|断言|证明|声称|认定|说|得出|[\s‘’“”\"*])*\Z"
    r"|\b(?:cannot|can't|does not|not enough to)(?: establish| conclude| prove| claim)?\s*[\"']?\Z",
    re.IGNORECASE,
)


def corpus_limits(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select tool observations which cannot establish exhaustive corpus coverage."""
    limits = []
    for observation in observations:
        if observation.get("tool") != "corpus_search":
            continue
        coverage = observation.get("coverage") or {}
        if (
            not observation.get("obtained")
            or coverage.get("processing") != "complete"
            or coverage.get("availability") in {None, "unknown"}
            or coverage.get("purity", {}).get("scope") == "bounded_candidates_not_corpus_absence"
            or coverage.get("native", {}).get("unknown_date_sources")
            or coverage.get("native", {}).get("unknown_date_source_count")
        ):
            limits.append(observation)
    return limits


def corpus_scope_findings(text: str, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return exact spans only when recorded retrieval limits contradict coverage wording."""
    if not corpus_limits(observations):
        return []
    findings = []
    for sentence_match in _SENTENCE.finditer(text):
        sentence = sentence_match.group()
        for match in _ABSOLUTE.finditer(sentence):
            prefix = sentence[max(0, match.start() - 40) : match.start()]
            if _QUALIFIED.search(prefix):
                continue
            findings.append(
                {
                    "rule": "corpus_scope_overstatement",
                    "reason": "Bounded/partial retrieval and unknown dates do not prove corpus-wide "
                    "absence, complete counts, or latestness. State what this search found instead.",
                    "match": match.group(),
                    "sentence": sentence,
                    "start": sentence_match.start(),
                    "end": sentence_match.end(),
                    "match_start": sentence_match.start() + match.start(),
                    "match_end": sentence_match.start() + match.end(),
                }
            )
    return findings


def compact_corpus_limits(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain conservative scope constraints once; full query diagnostics stay in the job."""
    limits = corpus_limits(observations)
    if not limits:
        return []
    unknown_dates = any(
        (o.get("coverage") or {}).get("native", {}).get("unknown_date_sources")
        or (o.get("coverage") or {}).get("native", {}).get("unknown_date_source_count")
        for o in limits
    )
    return [{
        "tool": "corpus_search", "obtained": all(o.get("obtained") for o in limits),
        "coverage": {
            "processing": "partial", "availability": "unknown",
            "purity": {"scope": "bounded_candidates_not_corpus_absence"},
            "native": {"unknown_date_sources": bool(unknown_dates)},
        },
        "limited_observations": len(limits),
    }]
