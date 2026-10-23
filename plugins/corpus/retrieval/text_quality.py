"""Conservative display signals; never rewrite authoritative evidence text."""

from __future__ import annotations

import re
import unicodedata


def comparison_text(text: str) -> str:
    """Ignore PDF layout/control artifacts only in comparisons, not in delivery."""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKC", text).casefold()
        if not ch.isspace() and unicodedata.category(ch) not in {"Cc", "Cf"}
    )


_DISCLOSURE = re.compile(
    r"分析师(?:声明|承诺|在本报告中)|每位负责撰写本研究报告|"
    r"免责声明|法律声明|利益冲突披露|"
    r"(?:本报告|本研究报告).{0,35}(?:版权|仅供.{0,12}客户|不构成.{0,12}投资建议)"
)
_DISCLOSURE_QUERY = re.compile(r"声明|免责|版权|合规|利益冲突|持股|分析师|评级定义")


def noise_reason(text: str, query: str) -> str | None:
    """Recognize boilerplate and detached axes, not risks or quantitative prose.

    Explicit requests for disclosures retain them. Numeric scraps require many
    numeric-only lines and almost no prose; readable table rows are not excluded.
    """
    normalized = comparison_text(text)
    if not _DISCLOSURE_QUERY.search(query) and _DISCLOSURE.search(normalized):
        return "disclosure"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    numeric = sum(bool(re.fullmatch(r"[\d\s.,%％/+:—–-]+", line)) for line in lines)
    letters = sum(ch.isalpha() for ch in normalized)
    if (
        numeric >= 6
        and numeric >= len(lines) * 0.65
        and letters < 50
        and not re.search(r"[。！？!?；;]", text)
    ):
        return "detached_chart_axes"
    return None
