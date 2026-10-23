"""Query-local precision gate after bounded retrieval, before agent delivery.

No index mutations, extra retrieval/model calls or invented aliases. This gate
compares lexical topic coverage, not semantic answerability. Retained sources
keep their original block order and full locator scope; low confidence queries
and the leading semantic source remain recoverable rather than claiming absence.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from plugins.corpus.retrieval.display import _coverage, _matches, query_terms, substantive_text
from plugins.corpus.retrieval.native import NativeBlock
from plugins.corpus.retrieval.text_quality import comparison_text

REVISION = "native-purity-v1"
# Relative to the best actual source in this request, not to RRF's rank score.
# Only active with at least three observed topic terms and six covered characters.
MIN_RELATIVE_COVERAGE = 0.4
_GENERIC_NAME_PARTS = frozenset(
    {"科技", "技术", "股份", "集团", "公司", "有限", "责任", "证券", "银行", "保险"}
)


def _company_topic(term: str, company: str) -> bool:
    # Avoid turning a province or an arbitrary interior bigram into a company.
    stem = re.sub(r"(?:股份有限公司|有限公司|科技|技术|股份|集团|银行|保险)$", "", company)
    return term in (company, stem) or company.endswith(term)


def _companies(names: Sequence[str]) -> set[str]:
    result = set(re.findall(r"-([\u4e00-\u9fff]{2,12})-\d{6}(?=[-_.])", "\n".join(names)))
    for name in names:
        match = re.match(r"^([\u4e00-\u9fff]{2,12})_投委会", name)
        if match:
            result.add(match[1])
    return result


@dataclass(frozen=True)
class SourceDecision:
    build_id: str
    keep: bool
    reason: str
    coverage: int


def select_sources(
    groups: Mapping[str, Sequence[NativeBlock]],
    chunks: Mapping[tuple[str, str], dict[str, Any]],
    query: str,
    lexemes: Sequence[str],
    *,
    names: Mapping[str, Sequence[str]],
) -> tuple[SourceDecision, ...]:
    """Drop weak tails without backfilling or narrowing any retained fetch scope.

    Chunk context may establish an implicit subject but is never evidence. A
    source's score is its best chunk, not terms pooled across unrelated pages.
    Attributed company names identify literal topic hints and support implicit
    subjects; a missing subject alone is not proof of irrelevance. Strong facet
    coverage, the leading source and partial comparisons stay conservative.
    """
    terms = tuple(t for t in query_terms(query, lexemes) if not t.isdecimal())
    companies = {sid: _companies(values) for sid, values in names.items()}
    identities = set().union(*companies.values()) if companies else set()
    # Literal query tokens occurring in a unique, attributed company name are
    # topic hints, not new aliases. Generic/shared fragments cannot constrain.
    subjects = tuple(
        t
        for t in terms
        if len(t) >= 2
        and t not in _GENERIC_NAME_PARTS
        and sum(_company_topic(t, company) for company in identities) == 1
    )
    facets = tuple(t for t in terms if t not in subjects)
    # A compound question can legitimately be answered across sources. Literal
    # coordinated topics provide a recall rescue, never an exclusion condition.
    coordinated = tuple(
        t
        for t in terms
        if len(t) >= 2
        and re.search(
            r"(?:以及|和|与|及|、|或者|或|\band\b|\bor\b)\s*" + re.escape(t),
            query.casefold(),
        )
    )
    features = []
    for bid, blocks in groups.items():
        score = count = 0
        has_prose = False
        subject_support = False
        partial_topic = False
        for block in blocks:
            body = substantive_text(block, query)
            if not comparison_text(body):
                continue
            has_prose = True
            partial_topic |= bool(_matches(body, coordinated))
            chunk = chunks[bid, block.chunk_id]
            # Remove raw body from index_text so rejected boilerplate cannot vote.
            indexed = chunk.get("index_text", "")
            raw = chunk.get("search_text", "")
            context = indexed[: -len(raw)] if raw and indexed.endswith(raw) else ""
            text = body + "\n" + context + "\n" + (chunk.get("title_text") or "")
            matching = _matches(text, terms)
            score = max(score, len(_coverage(query, matching)))
            count = max(count, len(matching))
            subject_support |= bool(_matches(body, subjects)) or bool(
                _matches(context + (chunk.get("title_text") or ""), subjects)
                and len(_coverage(query, _matches(body, facets))) >= 4
            )
        owners = companies.get(blocks[0].source_id, set()) if blocks else set()
        company_hint = any(_company_topic(t, company) for t in subjects for company in owners)
        features.append(
            (bid, score, count, has_prose, company_hint, subject_support, partial_topic)
        )
    best = max((f[1] for f in features), default=0)
    active = best >= 6 and max((f[2] for f in features), default=0) >= 3
    decisions = []
    subject_gate = active and bool(subjects) and any(f[4] or f[5] for f in features)
    for i, (bid, score, _, prose, company, subject_support, partial_topic) in enumerate(features):
        if not prose:
            reason, keep = "structural_noise", False
        elif not active:
            reason, keep = "insufficient_signal", True
        elif subject_gate and not (company or subject_support) and i != 0 and score < best * 0.75:
            reason, keep = "subject_not_observed", False
        elif score >= best * MIN_RELATIVE_COVERAGE:
            reason, keep = "topic_coverage", True
        elif partial_topic:
            reason, keep = "partial_topic", True
        elif company:
            reason, keep = "source_subject_hint", True
        elif i == 0:
            reason, keep = "semantic_anchor", True
        else:
            reason, keep = "weak_topic_coverage", False
        decisions.append(SourceDecision(bid, keep, reason, score))
    return tuple(decisions)
