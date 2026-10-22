"""Explicit pilot index and bounded native evidence, separate from legacy fetches.

An index is an operator-frozen, native-source allowlist, not an OCR detector.
Only exact raw-unit slices are returned; search projections are never quoted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from plugins.corpus.preparation.read_pg import IntegrityError
from plugins.corpus.retrieval.embedding import validate_vector

SAFE_KINDS = frozenset({"paragraph", "quote", "list_item", "heading", "title"})


def normalized(text: str) -> str:
    """Match the pilot projection's whitespace and percentage normalization only."""
    return "".join(text.replace("%", " ").replace("％", " ").split())


@dataclass(frozen=True)
class NativeSpan:
    """Coordinates in an authoritative raw unit; text occurs once in the block."""

    unit_id: str
    page: int | None
    start: int
    end: int
    raw_sha256: str


@dataclass(frozen=True)
class NativeSlice(NativeSpan):
    """Internal mapping result before assembling the public evidence block."""

    text: str


@dataclass(frozen=True)
class NativeBlock:
    source_id: str
    build_id: str
    chunk_id: str
    published: str | None
    text: str
    slices: tuple[NativeSpan, ...]


@dataclass(frozen=True)
class NativeResult:
    query: str
    index_id: str
    blocks: tuple[NativeBlock, ...]
    body_characters: int
    char_budget: int
    block_limit: int
    cutoff: str
    unknown_date_sources: tuple[str, ...]
    first_anchor_preserved: bool
    retrieval_mode: str = "hybrid"
    fallback_reason: str | None = None


def raw_slices(projection: str, units: list[dict[str, Any]]) -> tuple[NativeSlice, ...]:
    """Map all projected characters to increasing verified raw-unit coordinates.

    Omissions in a clean view become separate slices. A long unit is not expanded
    beyond the matching chunk. Unmappable text fails instead of falling back.
    """
    target = normalized(projection)
    chars: list[str] = []
    positions: list[tuple[int, int]] = []
    for i, unit in enumerate(units):
        raw = unit["raw_text"]
        if (
            unit["status"] != "kept"
            or unit["kind"] not in SAFE_KINDS
            or hashlib.sha256(raw.encode()).hexdigest() != unit["content_hash"]
        ):
            raise IntegrityError("native_unit_not_verified_or_eligible")
        for offset, char in enumerate(raw):
            if not char.isspace() and char not in "%％":
                chars.append(char)
                positions.append((i, offset))
    source = "".join(chars)
    if not target:
        raise IntegrityError("native_empty_projection")
    direct = source.find(target)
    if direct >= 0:
        matched = positions[direct : direct + len(target)]
    else:
        matched = []
        consumed = 0
        for block in SequenceMatcher(None, source, target, autojunk=False).get_matching_blocks():
            if not block.size:
                continue
            if block.b != consumed:
                raise IntegrityError("native_projection_not_mappable")
            matched.extend(positions[block.a : block.a + block.size])
            consumed += block.size
        if consumed != len(target):
            raise IntegrityError("native_projection_not_mappable")
    ranges: list[tuple[int, int, int]] = []
    for i, offset in matched:
        if (
            ranges
            and ranges[-1][0] == i
            and not normalized(units[i]["raw_text"][ranges[-1][2] : offset])
        ):
            previous = ranges[-1]
            ranges[-1] = (i, previous[1], offset + 1)
        else:
            ranges.append((i, offset, offset + 1))
    result = []
    for i, start, end in ranges:
        unit = units[i]
        raw = unit["raw_text"]
        # The index drops percentages; the exact evidence must keep them.
        while end < len(raw) and raw[end] in "%％":
            end += 1
        result.append(
            NativeSlice(
                unit["unit_id"],
                unit["location"].get("page"),
                start,
                end,
                unit["content_hash"],
                raw[start:end],
            )
        )
    if normalized("\n".join(s.text for s in result)) != target:
        raise IntegrityError("native_projection_roundtrip_failed")
    return tuple(result)


def select_native(
    ranked: list[tuple[str, str]],
    blocks: dict[tuple[str, str], NativeBlock],
    *,
    char_budget: int,
    limit: int,
) -> tuple[NativeBlock, ...]:
    """Budget the returned raw text, never snippets, vectors, or whole units."""
    if not 1 <= char_budget <= 16000 or not 1 <= limit <= 20:
        raise ValueError("native_budget_requires_1_to_16000_chars_and_1_to_20_blocks")
    used = 0
    seen = set()
    result = []
    for key in ranked:
        if key in seen:
            continue
        seen.add(key)
        block = blocks[key]
        if used + len(block.text) > char_budget:
            continue
        result.append(block)
        used += len(block.text)
        if len(result) == limit:
            break
    return tuple(result)


class NativeIndex:
    """Hash-checked pilot bundle. No queries or gold annotations belong in it."""

    def __init__(self, manifest_path: Path) -> None:
        manifest_path = manifest_path.resolve()
        raw = manifest_path.read_bytes()
        self.index_id = hashlib.sha256(raw).hexdigest()
        self.manifest: dict[str, Any] = json.loads(raw)
        if self.manifest.get("schema") != "native-evidence-pilot-1":
            raise ValueError("native_index_schema_unsupported")
        self.target: str = self.manifest["target_db"]
        if not self.target.startswith("vector_pilot_"):
            raise ValueError("native_index_requires_pilot_target")
        expected_files = {"chunks.json", "units.json", "vectors.json", "dates.json"}
        if set(self.manifest["files"]) != expected_files:
            raise ValueError("native_index_files_invalid")
        payload = {}
        for name, expected_hash in self.manifest["files"].items():
            path = (manifest_path.parent / name).resolve()
            if path.parent != manifest_path.parent:
                raise ValueError("native_index_path_escape")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != expected_hash:
                raise IntegrityError("native_index_file_hash_mismatch")
            payload[name] = json.loads(data)
        self.chunks: list[dict[str, Any]] = payload["chunks.json"]
        self.units = {(u["build_id"], u["unit_id"]): u for u in payload["units.json"]}
        self.vectors: dict[str, Any] = payload["vectors.json"]
        self.dates: list[dict[str, Any]] = payload["dates.json"]
        allowed = set(self.manifest["source_allowlist"])
        if allowed.intersection(self.manifest["excluded_source_ids"]):
            raise IntegrityError("native_source_scope_conflict")
        if {d["source_id"] for d in self.dates} != allowed or len(self.dates) != len(allowed):
            raise IntegrityError("native_source_dates_incomplete")
        publications = {p[0]: p[1] for p in self.manifest["publications"]}
        seen = set()
        for chunk in self.chunks:
            key = chunk["build_id"], chunk["chunk_id"]
            if (
                key in seen
                or chunk["source_id"] not in allowed
                or chunk["kind"] == "table"
                or publications.get(chunk["source_id"]) != chunk["build_id"]
            ):
                raise IntegrityError("native_chunk_scope_invalid")
            seen.add(key)
            if hashlib.sha256(chunk["search_text"].encode()).hexdigest() != chunk["input_hash"]:
                raise IntegrityError("native_chunk_text_hash_mismatch")
            for uid in chunk["unit_refs"]:
                if not self.units[key[0], uid]["eligible"]:
                    raise IntegrityError("native_unit_scope_invalid")
            validate_vector(
                self.vectors[chunk["input_hash"]]["vector"], self.manifest["dimensions"]
            )
