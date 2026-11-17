"""Refuse a finding whose statement claims more than the text it cites.

The failure this targets is narrow and measured: a statement drops the limiter
that bounded it in the source ("部分数据中心订单存在 20%–30% 的溢价，但并未将该
溢价套用于全部方案组合" archived as "数据中心订单 20%–30% 的溢价可能收窄"), so the
record now reads as covering every combination. The numbers are right; the scope is
not, and once the body retires there is nothing left to notice it.

Two grades, deliberately unequal:

``scope``     narrows *which cases* apply (部分 / 未将该 / 套用于全部 / 大多数 /
              并非 / 不适用 / 不包括). Missing from the statement, the claim is
              wider than its evidence — this blocks the install.
``emphasis``  only carries contrast (仅). The number is unchanged, so it is
              reported by :func:`audit_statement` and never blocks anything.

Why a sentence pair and not the whole excerpt: the first draft scanned the whole
cited chunk and flagged 11 of 22 findings, every one a false positive, because a
page contains ``约`` and ``部分`` somewhere regardless of what the statement says.
A limiter is only attributable when the cited sentence makes the same numeric
assertion as the statement.

This is a rule set, not a semantic checker. It finds one shape of error — a
limiter present in the source and absent from the statement — and says nothing
about subject, period, denominator, or forecast-versus-actual mismatches.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from frontier_agent.core.runtime.reading.contract import Finding, ValidationIssue

#: canonical limiter -> accepted surface variants.
SCOPE_LIMITS: dict[str, tuple[str, ...]] = {
    "部分": ("部分",),
    "大多数": ("大多数", "多数"),
    "未将该": ("未将该", "并未将该"),
    "套用于全部": ("套用于全部", "套用于所有"),
    "不适用": ("不适用",),
    "不包括": ("不包括", "不含"),
    "并非": ("并非",),
}

#: contrast markers: they change the emphasis, not the coverage.
EMPHASIS_LIMITS: dict[str, tuple[str, ...]] = {"仅": ("仅",)}

#: markers that must sit immediately before a shared number.
PRECISION_MARKERS: dict[str, tuple[str, ...]] = {
    "约": ("约",),
    "至少": ("至少",),
    "超过": ("超过",),
    "不足": ("不足",),
    "近": ("近",),
}

#: Issue code that blocks installation. Stable: traces and tests match on it.
SCOPE_ISSUE_CODE = "statement_scope_expanded"

_QUARTER = re.compile(r"\d+Q\d+")
_SENTENCE = re.compile(r"[。！？；\n]")
_DECIMAL = re.compile(r"\d+(?:\.\d+)?")


def numbers_of(text: str) -> set[str]:
    """Decimal tokens, with quarter notation (``3Q26``) removed first.

    ``3Q26`` and ``2026 财年第三季度`` are the same fact written differently;
    counting the ``3`` as unanchored is notation, not fabrication.
    """
    return set(_DECIMAL.findall(_QUARTER.sub("", text or "")))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def audit_statement(statement: str, cited: str) -> dict[str, Any]:
    """Compare one statement against the text it cites.

    ``cited`` is every excerpt attached to the finding, concatenated; the pairing
    step decides which sentences are about the same assertion.
    """
    statement_text = _squash(statement)
    cited_text = _squash(cited)
    wanted = numbers_of(statement_text)
    unanchored = sorted(token for token in wanted if token not in cited_text)

    sentences = [part for part in _SENTENCE.split(cited_text) if part]
    paired = [part for part in sentences if any(token in part for token in wanted)]

    limits: list[dict[str, str]] = []
    for severity, table in (("scope", SCOPE_LIMITS), ("emphasis", EMPHASIS_LIMITS)):
        for canonical, variants in table.items():
            in_source = any(variant in part for part in paired for variant in variants)
            in_statement = any(variant in statement_text for variant in variants)
            if in_source and not in_statement:
                limits.append({"limiter": canonical, "severity": severity})

    precision: list[str] = []
    for token in wanted:
        for sentence in paired:
            start = 0
            while (pos := sentence.find(token, start)) >= 0:
                start = pos + 1
                window = sentence[max(0, pos - 6) : pos]
                for canonical, variants in PRECISION_MARKERS.items():
                    if any(variant in window for variant in variants) and (
                        canonical not in statement_text
                    ):
                        precision.append(f"{canonical}{token}")

    return {
        "unanchored_numbers": unanchored,
        "limits": limits,
        "numbers_relaxed": sorted(set(precision)),
        "paired_sentences": len(paired),
        "verdict": _verdict(unanchored, limits, precision),
    }


def _verdict(
    unanchored: list[str], limits: list[dict[str, str]], precision: list[str]
) -> str:
    if unanchored:
        return "number_not_in_source"
    if any(item["severity"] == "scope" for item in limits):
        return "scope_expanded"
    if limits or precision:
        return "emphasis_only"
    return "clean"


def scope_issues(finding: Finding, quoted: str) -> list[ValidationIssue]:
    """Validation hook: block installation when the statement widened its evidence.

    Returns an empty list for anything else — an unanchored number is *reported*
    by :func:`audit_statement` but not gated here, because numeric mismatch has
    several innocent causes (rounding in the statement, a number composed across
    two sentences) and gating on it would block archiving for notation. Scope is
    the case with no innocent reading: the source's own words narrowed the claim.

    ``condition`` counts as part of the claim. A record that moves "不含并购贡献"
    out of the prose and into its structured condition field has kept the limiter,
    and flagging that would block archiving for good housekeeping.
    """
    from frontier_agent.core.runtime.reading.contract import ValidationIssue

    claim = finding.statement
    if finding.condition.strip():
        claim = f"{claim}；{finding.condition}"
    result = audit_statement(claim, quoted)
    if result["verdict"] != "scope_expanded":
        return []
    dropped = [
        item["limiter"] for item in result["limits"] if item["severity"] == "scope"
    ]
    return [
        ValidationIssue(
            SCOPE_ISSUE_CODE,
            f"{finding.finding_id} 的表述丢失了原文的适用范围限定"
            f"（{'、'.join(dropped)}），不得据此替换正文",
            finding.finding_id,
        )
    ]
