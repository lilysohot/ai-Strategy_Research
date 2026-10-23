"""Query-guided, bounded verbatim previews. No retrieval, database or model calls.

Selection is lexical, not an assertion that a passage answers the question.
Offsets refer to the verified NativeBlock.text; generated labels are not evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from plugins.corpus.preparation.negative_query import abstain_content_lexemes
from plugins.corpus.retrieval.passage_coverage import PassageCoverage, answer_roles, content_query
from plugins.corpus.retrieval.text_quality import comparison_text, noise_reason

# Language scaffolding only: no financial indicators, companies or product vocabulary.
_FILLER = re.compile(r"请问|请|如何|为什么|为何|哪些|多少|什么|是否|怎么样|怎样|怎么|是多少|你好")
# Semicolons link clauses of one explanation; do not drop a limitation after one.
_BOUNDARY = re.compile(r'[。！？!?][”’」』"]*|(?<!\d)\.(?!\d)[”’"]*|\n[ \t]*\n')
_DEPENDENT = re.compile(r"^\s*(?:该|其|上述|这些|这种|这个|因此|由此|其中|这意味着)")
_QUALIFIER = re.compile(
    r"^\s*(?:但|然而|不过|其中|若|如果|除非|仅|需要注意|值得注意|前提|这意味着|[一二三四五六七八九十]是)"
)
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n|(?m:^[ \t]*[•●▪■\uf06e][ \t]*(?:\n|$))")
_SENTENCE_END = re.compile(r'[。！？!?][”’」』"]*\s*$|(?<!\d)\.[”’"]*\s*$')
_NUMBERED_LINE = re.compile(r"(?m)^\s*\d+[.)、]\s*\S")


@dataclass(frozen=True)
class Passage:
    block: int
    start: int
    end: int
    complete: bool = True


def _norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


def query_terms(query: str, lexemes: Sequence[str] = ()) -> tuple[str, ...]:
    """Reuse PG terms in production; bounded character grams support offline callers."""
    source = unicodedata.normalize("NFKC", _FILLER.sub(" ", query)).casefold()
    # Do not let tokenizer artifacts such as 年半 cross a date/content boundary.
    source = re.sub(r"(?<=\d)[年月日]", " ", source)
    clean = _norm(source)
    terms = [_norm(t) for t in abstain_content_lexemes(lexemes) if _norm(t) in clean]
    for token in re.findall(r"[a-z0-9]+(?:[.-][a-z0-9]+)*|[\u3400-\u9fff]+", source):
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            # Supplements PG's single-character splits (e.g. 液/冷) without a domain lexicon.
            terms.extend(token[i : i + 2] for i in range(len(token) - 1))
        else:
            terms.append(token)
    unique = tuple(dict.fromkeys(t for t in terms if t and any(c.isalnum() for c in t)))
    return tuple(
        t
        for t in unique
        if not (
            t.isascii() and any(t != other and t in other and other.isascii() for other in unique)
        )
    )


def _coverage(query: str, terms: frozenset[str] | set[str]) -> set[int]:
    """Count a query character once even when matching terms overlap."""
    text = _norm(query)
    covered = set()
    for term in terms:
        for match in re.finditer(re.escape(term), text):
            covered.update(range(match.start(), match.end()))
    # A four-digit year is one temporal signal, not four independent topic matches.
    for year in re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text):
        covered.difference_update(range(year.start() + 1, year.end()))
    return covered


def _matches(text: str, terms: tuple[str, ...]) -> frozenset[str]:
    normalized = _norm(text)
    words = unicodedata.normalize("NFKC", text).casefold()
    return frozenset(
        term
        for term in terms
        if (
            re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", words)
            if term.isascii()
            else term in normalized
        )
    )


def _regions(block: Any) -> list[tuple[int, int, int | None]]:
    """Do not silently join separate authoritative raw slices."""
    spans = getattr(block, "slices", ())
    if spans and all(hasattr(s, "start") and hasattr(s, "end") for s in spans):
        offset = 0
        regions = []
        for span in spans:
            end = offset + span.end - span.start
            regions.append((offset, end, span.page))
            offset = end + 1  # native raw slices are joined with a single newline
        if offset - 1 == len(block.text):
            return regions
    # No inferred page if a mapping is incomplete or ambiguous.
    page = spans[0].page if len(spans) == 1 else None
    return [(0, len(block.text), page)]


def _reading_regions(block: Any) -> list[tuple[int, int]]:
    """Recover wrapped text only across verified complete, ordinal-adjacent units.

    The visible label still declares cross-unit excerpts. Gaps and unknown IDs
    remain separate; the native handle and its raw slices are never expanded.
    """
    regions = _regions(block)
    spans = getattr(block, "slices", ())
    lengths = getattr(block, "unit_lengths", ())
    if len(spans) != len(regions) or len(lengths) != len(spans):
        return [(a, b) for a, b, _ in regions]
    joined: list[tuple[int, int]] = []
    for i, (a, b, _) in enumerate(regions):
        adjacent = False
        if i:
            prev, current = spans[i - 1], spans[i]
            previous_id = re.fullmatch(r"unit:(\d+)", prev.unit_id)
            current_id = re.fullmatch(r"unit:(\d+)", current.unit_id)
            adjacent = bool(
                previous_id
                and current_id
                and int(current_id[1]) == int(previous_id[1]) + 1
                and prev.end == lengths[i - 1]
                and current.start == 0
            ) or (prev.unit_id == current.unit_id and prev.end == current.start)
        if adjacent:
            joined[-1] = (joined[-1][0], b)
        else:
            joined.append((a, b))
    return joined


def _sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    result = []
    cursor = start
    for match in _BOUNDARY.finditer(text, start, end):
        stop = match.end()
        if text[cursor:stop].strip():
            result.append((cursor, stop))
        cursor = stop
    if text[cursor:end].strip():
        result.append((cursor, end))
    return result


def _paragraph_regions(block: Any) -> list[tuple[int, int]]:
    """Use source-unit paragraph boundaries, retaining verified wrapped sentences.

    A complete sentence at the end of a raw unit is a paragraph boundary. A
    wrapped sentence may cross adjacent units only under _reading_regions' rules.
    Bare PDF line wraps are never interpreted as paragraph boundaries.
    """
    raw_regions = _regions(block)
    result = []
    for start, end in _reading_regions(block):
        cuts = {start, end}
        for a, b, _ in raw_regions:
            if (
                start <= a < b < end
                and _SENTENCE_END.search(block.text[a:b])
                and not _QUALIFIER.match(block.text[b + 1 : end])
                and not _DEPENDENT.match(block.text[b + 1 : end])
            ):
                cuts.add(b + 1)
        for match in _PARAGRAPH_BREAK.finditer(block.text, start, end):
            cuts.update((match.start(), match.end()))
        boundaries = sorted(cuts)
        for a, b in pairwise(boundaries):
            raw = block.text[a:b]
            if raw.strip() and not _PARAGRAPH_BREAK.fullmatch(raw):
                result.append((a, b))
    return result


def _navigation(text: str) -> bool:
    """Detect numbered topic lists, not substantive numbered prose statements."""
    # Topic headings can be questions; a question mark does not make a TOC prose.
    return len(_NUMBERED_LINE.findall(text)) >= 3 and "。" not in text


def _heading_only(text: str) -> bool:
    """Display preference only; unpunctuated numeric/table evidence remains eligible."""
    return not re.search(r"[。！？!?；;]|(?<!\d)\.(?!\d)|\d|[:：=]", text)


def substantive_text(block: Any, query: str) -> str:
    """Scoring-only view; preserve source text and offsets for actual delivery."""
    return "\n".join(
        block.text[a:b]
        for a, b in _paragraph_regions(block)
        if noise_reason(block.text[a:b], query) is None
    )


def _candidates(blocks: Sequence[Any], chars_per_block: int) -> list[Passage]:
    """Prefer bounded source paragraphs; long/unstructured text uses sentence windows.

    Paragraph selection sees the explanation's combined relevance, so a short
    fragment repeating query words cannot split the explanation into losing seeds.
    Context inside a paragraph does not need to add new query terms.
    """
    result = []
    for index, block in enumerate(blocks):
        spans = getattr(block, "slices", ())
        mapped = bool(spans) and all(hasattr(s, "start") and hasattr(s, "end") for s in spans)
        structured = mapped or bool(_PARAGRAPH_BREAK.search(block.text))
        for start, end in _paragraph_regions(block):
            raw = block.text[start:end]
            if structured and end - start <= chars_per_block and _SENTENCE_END.search(raw):
                result.append(Passage(index, start, end))
                continue
            sentences = _sentences(block.text, start, end)
            for i, (a, b) in enumerate(sentences):
                # Keep explicit dependencies with the matching sentence, within its raw slice.
                low = i
                while low and (
                    _DEPENDENT.match(block.text[sentences[low][0] : sentences[low][1]])
                    or _QUALIFIER.match(block.text[sentences[low][0] : sentences[low][1]])
                ):
                    low -= 1
                high = i
                if block.text[a:b].rstrip().endswith(("？", "?")) and i + 1 < len(sentences):
                    high += 1  # a repeated question is context; show its explanation too
                while high + 1 < len(sentences) and _QUALIFIER.match(
                    block.text[sentences[high + 1][0] : sentences[high + 1][1]]
                ):
                    high += 1
                result.append(Passage(index, sentences[low][0], sentences[high][1]))
    return result


def _excerpt(text: str, passage: Passage, terms: tuple[str, ...], budget: int) -> Passage:
    """An oversized unit is an explicitly partial excerpt, never a 'complete sentence'."""
    if passage.end - passage.start <= budget:
        return passage
    # Map normalized matching positions back to the unchanged source text.
    chars: list[str] = []
    offsets: list[int] = []
    for index in range(passage.start, passage.end):
        for ch in _norm(text[index]):
            chars.append(ch)
            offsets.append(index)
    normalized = "".join(chars)
    positions = [normalized.find(t) for t in terms if t in normalized]
    anchors = [offsets[position] for position in positions] or [passage.start]
    windows = []
    for anchor in anchors:
        start = max(passage.start, min(anchor - budget // 4, passage.end - budget))
        end = min(start + budget, passage.end)
        matched = _matches(text[start:end], terms)
        # An early year alone must not hide a later subject in a long sentence.
        score = (sum(not term.isdecimal() for term in matched), len(matched), -start)
        windows.append((score, start, end))
    _, start, end = max(windows)
    return Passage(passage.block, start, end, False)


def select_passages(
    blocks: Sequence[Any],
    query: str,
    *,
    lexemes: Sequence[str] = (),
    max_blocks: int = 1,
    chars_per_block: int = 180,
) -> tuple[list[Passage], bool]:
    """Choose complete source paragraphs, with sentence windows for oversized text.

    Discount query aspects repeated throughout the source and across selected
    passages. A new block may explain already-covered terms; lexical novelty is
    not required. Source admission uses the unchanged lexical helpers above.
    With multiple display slots, retain a relevant prose anchor from the first
    retrieved block before adding lexical complements. Otherwise display would
    throw away semantic retrieval's first hit using only word overlap again.
    Original RRF order and handles never change. Unmatched queries retain the
    first block as a labelled fallback.
    """
    if not blocks or chars_per_block < 1 or max_blocks < 1:
        return [], False
    terms = query_terms(content_query(query), lexemes)
    candidates = [
        p
        for p in _candidates(blocks, chars_per_block)
        if not any(
            a <= p.start and p.end <= b and noise_reason(blocks[p.block].text[a:b], query)
            for a, b in _paragraph_regions(blocks[p.block])
        )
    ]
    navigation = [
        any(
            a <= p.start and p.end <= b and _navigation(blocks[p.block].text[a:b])
            for a, b in _paragraph_regions(blocks[p.block])
        )
        for p in candidates
    ]
    wants_navigation = bool(re.search(r"目录|章节|议程|contents|agenda", query, re.I))
    matches = [_matches(blocks[p.block].text[p.start : p.end], terms) for p in candidates]
    coverage = PassageCoverage(
        [blocks[p.block].text[p.start : p.end] for p in candidates],
        [
            _coverage(query, matching) | answer_roles(query, blocks[p.block].text[p.start : p.end])
            for p, matching in zip(candidates, matches, strict=True)
        ],
    )
    topics = {t for t in terms if not t.isdecimal()}
    years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", query))
    selected: list[Passage] = []
    used: dict[int, int] = {}
    seen: set[str] = set()
    # Bound fragments per block as well as text; this is a display limit, not a semantic rule.
    while len(selected) < 3 * max_blocks:
        choices = []
        for order, (p, matching) in enumerate(zip(candidates, matches, strict=True)):
            if topics and not (matching & topics):
                continue  # a year alone cannot replace the requested subject
            if p.block not in used and len(used) >= max_blocks:
                continue
            if any(p.block == s.block and p.start < s.end and s.start < p.end for s in selected):
                continue
            remaining = chars_per_block - used.get(p.block, 0)
            if remaining <= 0 or (p.block in used and p.end - p.start > remaining):
                continue
            actual = _excerpt(blocks[p.block].text, p, terms, remaining)
            raw = blocks[p.block].text[actual.start : actual.end]
            actual_matches = _matches(raw, terms)
            if topics and not actual_matches & topics:
                continue
            if comparison_text(raw) in seen:
                continue
            # Prefer a complete dependency window when both alternatives cover the same terms.
            # Explicit conflicting years must not displace an available compatible passage.
            passage_years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", raw))
            conflict = bool(years and passage_years and not years & passage_years)
            positions = _coverage(query, actual_matches) | answer_roles(query, raw)
            score = coverage.score(raw, positions)
            if score <= 0:
                continue
            question_only = raw.rstrip().endswith(("？", "?"))
            # A quantitative statement breaks otherwise equal lexical ties. A bare year
            # does not qualify; this is not a domain-specific "answer" classifier.
            value_text = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", "", raw)
            has_value = bool(re.search(r"\d", value_text))
            choices.append(
                (
                    (
                        wants_navigation or not (navigation[order] or _heading_only(raw)),
                        not question_only,
                        not conflict,
                        score,
                        len(_coverage(query, actual_matches)),
                        actual.complete,
                        has_value,
                        -len(raw),
                        -order,
                    ),
                    actual,
                    actual_matches,
                    raw,
                )
            )
        if not choices:
            break
        if not selected and max_blocks > 1:
            # Do not reserve the retrieval anchor for a weak incidental match:
            # it must cover at least half as much query text as the best candidate.
            best_coverage = max(c[0][4] for c in choices)
            anchors = [
                c
                for c in choices
                if c[1].block == 0 and all(c[0][:3]) and c[0][4] * 2 >= best_coverage
            ]
            if anchors:
                choices = anchors
        _, selected_passage, matching, raw = max(choices, key=lambda c: c[0])
        selected.append(selected_passage)
        coverage.add(raw, _coverage(query, matching) | answer_roles(query, raw))
        used[selected_passage.block] = used.get(selected_passage.block, 0) + len(raw)
        seen.add(comparison_text(raw))
    if selected:
        return selected, True
    # No matching terms: retain original fused order, without claiming an answer was found.
    fallback = []
    for p in candidates:
        if p.block >= max_blocks or any(s.block == p.block for s in fallback):
            continue
        fallback.append(_excerpt(blocks[p.block].text, p, (), chars_per_block))
    return fallback, False


def compose_with_evidence(
    blocks: Sequence[Any],
    query: str = "",
    *,
    lexemes: Sequence[str] = (),
    max_blocks: int = 1,
    chars_per_block: int = 180,
) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Render once; bind complete verbatim passages to source and snippet offsets.

    Offsets count Unicode code points, before JSON escaping. Metadata refers to
    the existing context_locators array; no new handles or duplicate text.
    """
    from plugins.corpus.retrieval.embedding import text_hash

    passages, matched = select_passages(
        blocks, query, lexemes=lexemes, max_blocks=max_blocks, chars_per_block=chars_per_block
    )
    parts = []
    evidence = []
    offset = 0
    for p in passages:
        block = blocks[p.block]
        pages = tuple(
            dict.fromkeys(
                page
                for a, b, page in _regions(block)
                if a < p.end and p.start < b and page is not None
            )
        )
        label = f"【{p.block + 1}/{len(blocks)}"
        if pages:
            label += "｜p" + ",".join(map(str, pages))
        label += "】"
        # Explicit offsets are zero-based, end-exclusive in the fetched block text.
        location = f"〔原文字符{p.start}:{p.end}"
        if sum(a < p.end and p.start < b for a, b, _ in _regions(block)) > 1:
            location += "；跨原文单元"
        if not p.complete:
            location += "；句内节选，上下文不完整"
        location += "〕"
        raw = block.text[p.start : p.end]
        prefix = label + location
        if p.complete:
            evidence.append(
                {
                    "member": p.block + 1,
                    "start": p.start,
                    "end": p.end,
                    "snippet_start": offset + len(prefix),
                    "snippet_end": offset + len(prefix) + len(raw),
                    "text_chars": len(block.text),
                    "text_sha256": text_hash(block.text),
                    "quote_sha256": text_hash(raw),
                }
            )
        part = prefix + raw
        parts.append(part)
        offset += len(part) + 1
    hidden = len(blocks) - len({p.block for p in passages})
    if hidden:
        parts.append(f"（同源另有{hidden}块未展示，可按句柄补读）")
    if query and not matched:
        parts.append("（未找到明确的查询词匹配，保留原排序预览；不代表资料无答案）")
    return "\n".join(parts), tuple(evidence)


def compose(
    blocks: Sequence[Any],
    query: str = "",
    *,
    lexemes: Sequence[str] = (),
    max_blocks: int = 1,
    chars_per_block: int = 180,
) -> str:
    return compose_with_evidence(
        blocks, query, lexemes=lexemes, max_blocks=max_blocks, chars_per_block=chars_per_block
    )[0]
