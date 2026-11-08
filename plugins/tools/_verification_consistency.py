"""Conservative contradictions in a reviewer's own completion statements.

This is a rejection-only protocol check, not entailment or a semantic judge.
It examines neither source text nor topic vocabulary. Structured scope states
remain authoritative; absence of these bounded language patterns proves nothing.
"""

from __future__ import annotations

import re

_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|`[^`\n]*`')
_INCOMPLETE = re.compile(
    r"(?:尚未|未能|未|无法|不能)\s*(?:独立)?(?:核实|核验|验证|确认|取得|获取|取回|证实)"
    r"|\b(?:not|never)\s+(?:(?:yet|been|independently)\s+)*"
    r"(?:verified|validated|confirmed|established|retrieved|obtained)\b"
    r"|\b(?:cannot|could not|unable to)\s+(?:independently\s+)?"
    r"(?:verify|validate|confirm|establish|retrieve|obtain)\b",
    re.IGNORECASE,
)
_NEGATED = re.compile(r"(?:没有|不存在|并非|并无|不是|无|\bnot)\s*$", re.IGNORECASE)


def incomplete_review_statements(text: str) -> list[str]:
    """Identify explicit, unquoted incomplete-review assertions conservatively."""
    text = _QUOTED.sub(lambda m: " " * len(m.group()), text)
    return [
        match.group()
        for match in _INCOMPLETE.finditer(text)
        if not _NEGATED.search(text[max(0, match.start() - 16) : match.start()])
    ]
