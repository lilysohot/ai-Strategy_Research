"""Turn read corpus pages into a structured checkpoint the loop can retire behind.

This is the corpus side of task 05: the framework owns *when* a body may retire
and *that* the record is durable, but only this layer knows what an
``evidence_ref`` points at. The extractor therefore does three things and refuses
to do a fourth:

1. Build a digest of the bodies being retired, with every ``evidence_ref`` stated
   verbatim and every character counted against a budget.
2. Ask the model for findings that cite those refs.
3. Drop any finding that cites a ref not present in the digest, and record that
   it was dropped.

It does not repair a finding. A ``number`` missing its unit is passed through so
the contract rejects the whole checkpoint and the bodies stay where they are —
losing the unit silently is the exact failure this whole line of work exists to
stop, and "we dropped one and kept the rest" is that failure wearing a hat.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from frontier_agent.core.runtime.reading.contract import (
    Coverage,
    Finding,
    FindingKind,
    ReadingCheckpoint,
    SourceRange,
)
from frontier_agent.core.runtime.reading.stage import (
    ExtractionBounds,
    ExtractionScope,
    RetirableBody,
)
from frontier_agent.core.runtime.reading.store import JsonCheckpointStore
from plugins.corpus.tool_refs import ToolReferenceError, resolve_evidence_reference

logger = logging.getLogger(__name__)

__all__ = [
    "READING_EXTRACTION_PROMPT",
    "CorpusReadingExtractor",
    "ExtractionDigest",
    "default_checkpoint_store",
    "parse_extraction_reply",
]

#: Total characters of verbatim text one extraction may see. Beyond this the
#: remaining bodies are left out of the prompt and reported as a limitation
#: rather than silently dropped.
DEFAULT_DIGEST_BUDGET = 48_000

#: Refs resolved into ``SourceRange`` per checkpoint. A page of 76 fragments is
#: normal; a thousand is a sign the digest budget is misconfigured.
_MAX_SOURCE_RANGES = 256

READING_EXTRACTION_PROMPT = """你是研究归档器。下面是从语料中已读过的原文片段。请把它们转成结构化研究记录。

严格规则：
1. 只能使用给出的 evidence_ref。不得编造、不得改写引用；一条发现至少引用 1 个 ref。
2. kind 只能取：fact、number、date、condition、counter_evidence。
3. kind=number 必须同时给出 value、unit、period 三项，缺一不可。
   - value 只写数值本身（不要带单位）；unit 用原文写法，不得换算或补全；
   - period 写原文声明的期间（如 FY2025、2024Q3、截至 2025-03）。
   - 若原文只给了数值而没有单位或期间，就不要用 number，改用 fact 并把原文表述放进了 statement。
4. 若两段材料对同一口径给出不同数值，两条都要保留，并在各自的 contradicts 中写出对方的 finding_id。
5. 只记录原文明确写过的内容。不要推断、不要补充、不要写"可能"。
6. statement 用一句话复述该发现，保留限定条件；condition 写适用范围（如不含并购、欧盟口径）。

只输出 JSON，不要任何解释文字：
{"findings": [{"finding_id": "f1", "kind": "number", "statement": "...", "value": "...", "unit": "...", "period": "...", "condition": "...", "contradicts": [], "evidence_refs": ["ce:..."]}], "open_questions": ["..."]}"""


@dataclass(frozen=True)
class ExtractionDigest:
    """The verbatim text handed to the extractor, plus what was left out."""

    text: str
    refs: frozenset[str]
    fed_chars: int
    omitted_bodies: int = 0


@dataclass
class CorpusReadingExtractor:
    """LLM-backed extractor for corpus bodies.

    ``resolve`` defaults to the real receipt store, and is injectable so tests can
    describe references without disk. ``clock`` is not used: the stage owns the
    deadline, and a second one here would disagree with it.
    """

    llm: Any
    resolve: Callable[[str], dict[str, Any]] = resolve_evidence_reference
    digest_budget: int = DEFAULT_DIGEST_BUDGET
    max_source_ranges: int = _MAX_SOURCE_RANGES
    _range_cache: dict[str, SourceRange] = field(default_factory=dict, init=False)
    #: Usage of the most recent model call, or ``None`` when the provider reported
    #: none. The stage reads it so extraction cost is a measured number rather
    #: than an assumption; ``None`` is published as unknown, never as zero.
    last_usage: dict[str, Any] | None = field(default=None, init=False, repr=False)

    def scope(
        self,
        bodies: Sequence[RetirableBody],
        question: str,
    ) -> ExtractionScope:
        """Say whether these bodies can produce a citable record at all.

        Pure and IO-free: it renders the same digest ``__call__`` would, and
        reports its size and reference set. When no reference survives rendering,
        no finding the model could write is citable, so the extraction call is
        guaranteed to be discarded — declining here is the only outcome that does
        not pay for a known-empty result.
        """
        del question
        digest = self.build_digest(bodies)
        applicable = bool(digest.refs)
        return ExtractionScope(
            applicable=applicable,
            reason="" if applicable else "no_evidence_refs",
            digest_chars=len(digest.text),
            digest_budget=self.digest_budget,
            ref_count=len(digest.refs),
            omitted_bodies=digest.omitted_bodies,
            body_count=len(bodies),
        )

    async def __call__(
        self,
        bodies: Sequence[RetirableBody],
        question: str,
        bounds: ExtractionBounds,
    ) -> ReadingCheckpoint:
        self.last_usage = None
        digest = self.build_digest(bodies)
        prompt = (
            f"{READING_EXTRACTION_PROMPT}\n\n研究问题：{question}\n\n"
            f"最多记录 {bounds.max_findings} 条发现，总长度不超过 {bounds.record_limit} 字符。\n\n"
            f"原文片段：\n{digest.text}"
        )
        response = await self.llm.chat([{"role": "user", "content": prompt}])
        usage = getattr(response, "usage", None)
        if isinstance(usage, dict) and usage:
            self.last_usage = dict(usage)
        reply = getattr(response, "content", "") or ""
        findings, open_questions, dropped = parse_extraction_reply(reply, digest.refs)
        findings = findings[: max(1, bounds.max_findings)]

        limitations: list[str] = []
        if dropped:
            limitations.append(f"{dropped} 条发现因引用不在本次原文中而被丢弃")
        if digest.omitted_bodies:
            limitations.append(f"{digest.omitted_bodies} 段原文未进入提取输入，未读状态未消除")

        ranges = self._ranges_for(findings)
        return ReadingCheckpoint(
            checkpoint_id="",
            task_id="",
            question=question,
            findings=tuple(findings),
            sources=tuple(ranges),
            coverage=Coverage(
                read_ranges=tuple(ranges),
                unread_ranges=(),
                limitations=tuple(limitations),
                # Never true here. Completeness is a claim about a source range,
                # and this extractor only ever sees the pages it was handed.
                complete=False,
            ),
            open_questions=tuple(open_questions),
        )

    def build_digest(self, bodies: Sequence[RetirableBody]) -> ExtractionDigest:
        """Render bodies in reading order until the budget runs out.

        Each body contributes its fragments with the ref stated verbatim. A body
        that does not parse as a corpus payload is still included as raw text with
        no ref — the model can then record it as a ``fact`` citing nothing, which
        the contract rejects, which is the correct outcome for a body whose
        evidence cannot be identified.
        """
        chunks: list[str] = []
        refs: set[str] = set()
        used = 0
        omitted = 0
        for position, body in enumerate(bodies, start=1):
            rendered, body_refs, chars = _render_body(body, position)
            if used + chars > self.digest_budget and chunks:
                omitted += len(bodies) - position + 1
                break
            chunks.append(rendered)
            refs.update(body_refs)
            used += chars
        return ExtractionDigest(
            text="\n\n".join(chunks),
            refs=frozenset(refs),
            fed_chars=used,
            omitted_bodies=omitted,
        )

    def _ranges_for(self, findings: Sequence[Finding]) -> list[SourceRange]:
        ranges: list[SourceRange] = []
        seen: set[tuple[str, int, int]] = set()
        for finding in findings:
            for ref in finding.evidence_refs:
                cached = self._range_cache.get(ref)
                if cached is not None:
                    key = (cached.source_id, cached.start, cached.end)
                else:
                    try:
                        evidence = self.resolve(ref)
                    except (ToolReferenceError, OSError, ValueError) as exc:
                        logger.info("evidence ref %s did not resolve: %s", ref, exc)
                        continue
                    doc_id = str(evidence.get("doc_id") or "")
                    start = int(evidence.get("source_start") or 0)
                    end = int(evidence.get("source_end") or start)
                    cached = SourceRange(
                        source_id=doc_id,
                        # ``cv2:<digest>`` is content-addressed: a rebuilt document
                        # gets a new doc_id, so a stale record fails as an unknown
                        # source rather than silently quoting moved text.
                        version=doc_id.split(":", 1)[-1] if doc_id else "",
                        start=start,
                        end=end,
                        locator=str(evidence.get("locator") or ""),
                    )
                    self._range_cache[ref] = cached
                    key = (cached.source_id, cached.start, cached.end)
                if key in seen:
                    continue
                if len(ranges) >= self.max_source_ranges:
                    return ranges
                seen.add(key)
                ranges.append(cached)
        return ranges


def _render_body(body: RetirableBody, position: int) -> tuple[str, set[str], int]:
    """One body as prompt text. Returns ``(text, refs, chars)``."""
    header = f"### 原文 {position}（工具 {body.tool_name or 'unknown'}）"
    refs: set[str] = set()
    lines: list[str] = [header]
    payload: Any = None
    try:
        payload = json.loads(body.text)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        items = payload.get("items")
        rows = items if isinstance(items, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = row.get("text")
            if not isinstance(text, str):
                continue
            ref = row.get("evidence_ref")
            if isinstance(ref, str) and ref:
                refs.add(ref)
            location = row.get("location") or ""
            prefix = f"[{ref}]" if isinstance(ref, str) and ref else "[无引用]"
            if location:
                prefix = f"{prefix}{location}"
            lines.append(f"{prefix}\n{text}")
    else:
        # Not JSON: keep the bytes, cite nothing. A finding built on this will be
        # rejected by the contract, which is the honest outcome.
        lines.append(body.text)
    rendered = "\n".join(lines)
    return rendered, refs, len(rendered)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_extraction_reply(
    reply: str,
    known_refs: frozenset[str] | set[str],
) -> tuple[list[Finding], list[str], int]:
    """Parse the model's JSON, keeping only findings with a real citation.

    Returns ``(findings, open_questions, dropped)``. A finding whose refs are all
    unknown is dropped and counted — never rewritten to cite something else, and
    never kept with an empty ref list (which the contract would reject anyway,
    but keeping it would waste the whole checkpoint on one hallucination).
    """
    text = _FENCE.sub("", reply or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return [], [], 0
    try:
        payload = json.loads(text[start : end + 1])
    except ValueError:
        return [], [], 0
    if not isinstance(payload, dict):
        return [], [], 0

    known = set(known_refs)
    findings: list[Finding] = []
    dropped = 0
    raw_findings = payload.get("findings")
    for index, raw in enumerate(raw_findings if isinstance(raw_findings, list) else []):
        if not isinstance(raw, dict):
            dropped += 1
            continue
        refs = tuple(
            ref for ref in (raw.get("evidence_refs") or []) if isinstance(ref, str) and ref in known
        )
        if not refs:
            dropped += 1
            continue
        statement = str(raw.get("statement") or "").strip()
        if not statement:
            dropped += 1
            continue
        kind_value = str(raw.get("kind") or "").strip().lower()
        try:
            kind = FindingKind(kind_value)
        except ValueError:
            kind = FindingKind.FACT
        contradicts = tuple(
            str(other) for other in (raw.get("contradicts") or []) if isinstance(other, str)
        )
        findings.append(
            Finding(
                finding_id=str(raw.get("finding_id") or f"f{index + 1}"),
                kind=kind,
                statement=statement,
                evidence_refs=refs,
                source_id="",
                value=str(raw.get("value") or "").strip(),
                unit=str(raw.get("unit") or "").strip(),
                period=str(raw.get("period") or "").strip(),
                condition=str(raw.get("condition") or "").strip(),
                contradicts=contradicts,
            )
        )
    questions = [
        str(item) for item in (payload.get("open_questions") or []) if isinstance(item, str)
    ]
    return findings, questions, dropped


def default_checkpoint_store() -> JsonCheckpointStore:
    """Checkpoints live beside the evidence receipts they point at.

    Same root, same durability: an archive whose refs resolved yesterday must
    still resolve tomorrow, and putting the two in different places is how they
    drift apart. ``CORPUS_TOOL_REF_ROOT`` moves both at once.
    """
    configured = os.environ.get("CORPUS_TOOL_REF_ROOT", "").strip()
    root = (
        Path(configured).expanduser().resolve()
        if configured
        else Path(__file__).resolve().parents[2] / "data/corpus-tool-refs"
    )
    return JsonCheckpointStore(root / "reading")
