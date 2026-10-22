"""Opt-in native tool route: refresh published text, retain versioned slice handles.

The bundle supplies an explicit source scope and reusable embeddings only. Query
text, candidates, dates, and eligibility always come from current PG state.
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import psycopg

from plugins.corpus.preparation import read_pg
from plugins.corpus.preparation.chunk import normalize_search_text
from plugins.corpus.retrieval.embedding import text_hash, validate_vector
from plugins.corpus.retrieval.native import SAFE_KINDS, NativeIndex, normalized, raw_slices
from plugins.corpus.retrieval.native_pg import search_native
from plugins.corpus.retrieval.native_target import check_native_target

PREFIX = "chunk:native1/"
CAPTION = re.compile(
    r"^\s*(?:图表?\s*\d+|表\s*\d+|Figure\s*\d+|Table\s*\d+|资料来源\s*[:：]|数据来源\s*[:：])",
    re.I,
)


def enabled(target: str | None) -> bool:
    mode = os.getenv("CORPUS_NATIVE_RETRIEVAL", "off").strip()
    if mode not in ("off", "pilot", "release"):
        raise ValueError("CORPUS_NATIVE_RETRIEVAL must be off, pilot or release")
    if mode == "off":
        return False
    if mode == "pilot" and (not target or not target.startswith("vector_pilot_")):
        raise ValueError("native_tools_require_pilot_target")
    check_native_target(target)
    if target != os.getenv("CORPUS_NATIVE_TARGET_DB", ""):
        raise ValueError("native_tools_target_mismatch")
    return True


def configured_seed(target: str) -> NativeIndex:
    path = os.getenv("CORPUS_NATIVE_INDEX", "")
    if not path:
        raise ValueError("CORPUS_NATIVE_INDEX is required")
    seed = NativeIndex(Path(path))
    if seed.target != target:
        raise ValueError("native_seed_target_mismatch")
    if (
        not target.startswith("vector_pilot_")
        and seed.manifest["schema"] != "native-evidence-release-1"
    ):
        raise ValueError("native_release_bundle_required")
    return seed


def project(chunk: dict[str, Any], units: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The previously frozen native projection policy, applied to an active build."""
    core = [uid for uid in chunk["unit_refs"] if uid not in chunk["context_refs"]]
    if any(uid not in units for uid in core):
        raise read_pg.IntegrityError("native_projection_unit_missing")
    good = [uid for uid in core if units[uid]["eligible"]]
    if not good or chunk["kind"] == "table":
        return None
    bad = [uid for uid in core if uid not in good]
    text = chunk["search_text"]
    for uid in bad:
        u = units[uid]
        raw = normalize_search_text(u.get("clean_view") or u["raw_text"])
        if raw in text:
            text = text.replace(raw, "")
        elif normalized(raw) and normalized(raw) in normalized(text):
            raise read_pg.IntegrityError("native_nonliteral_mixed_unit")
        else:
            return None  # Split unsafe unit: do not guess its boundary.
    text = text.strip() if bad else text
    if not text.strip():
        return None
    raw_slices(text, [units[uid] for uid in good])
    return {
        **chunk,
        "search_text": text,
        "unit_refs": good,
        "context_refs": [],
        "input_hash": text_hash(text),
    }


def _units(cur: psycopg.Cursor, builds: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    cur.execute(
        "SELECT build_id,unit_id,kind,raw_text,location,content_hash,status,clean_view "
        "FROM corpus.corpus_units WHERE build_id=ANY(%s::text[])",
        (builds,),
    )
    result = {}
    for bid, uid, kind, raw, loc, h, status, clean in cur.fetchall():
        read_pg.verified_unit(bid, uid, raw, loc, h)
        result[bid, uid] = {
            "build_id": bid,
            "unit_id": uid,
            "kind": kind,
            "raw_text": raw,
            "location": loc,
            "content_hash": h,
            "status": status,
            "clean_view": clean,
            "eligible": status == "kept" and kind in SAFE_KINDS and not CAPTION.match(raw),
        }
    return result


def _date(names: list[str], reviewed: str | None, admitted: str | None) -> tuple[str | None, str]:
    if reviewed or admitted:
        return reviewed or admitted, "reviewed_metadata" if reviewed else "admission"
    values = set()
    for name in names:
        for match in re.finditer(r"(?<!\d)(20\d{2})[-._]?(\d{2})[-._]?(\d{2})(?!\d)", name):
            try:
                values.add(date(*map(int, match.groups())).isoformat())
            except ValueError:
                continue
    return (
        (next(iter(values)), "unambiguous_filename_date")
        if len(values) == 1
        else (None, "unknown_retained")
    )


def refresh_on(cur: psycopg.Cursor, seed: NativeIndex) -> NativeIndex:
    """Build a request-local index from one read snapshot; never cache result rows."""
    result = copy.copy(seed)
    result.manifest = copy.deepcopy(seed.manifest)
    cur.execute(
        "SELECT source_id,active_build_id,generation FROM corpus.corpus_publications ORDER BY source_id"
    )
    result.manifest["publications"] = [list(r) for r in cur.fetchall()]
    cur.execute(
        "SELECT p.source_id,p.active_build_id,s.original_names,"
        "m.confirmed_publication_date::text,a.metadata_snapshot->'report_publication'->>'value' "
        "FROM corpus.corpus_publications p JOIN corpus.corpus_sources s USING(source_id) "
        "JOIN corpus.corpus_builds b ON b.build_id=p.active_build_id "
        "JOIN corpus.corpus_admissions a ON a.decision_id=b.decision_id "
        "JOIN corpus.corpus_admissions live ON live.decision_id=p.current_decision_id "
        "JOIN corpus.corpus_admissions source_admission ON source_admission.decision_id=s.current_decision_id "
        "LEFT JOIN corpus_retrieval.source_metadata m ON m.source_id=p.source_id "
        "WHERE p.source_id=ANY(%s::text[]) AND live.decision='in_scope' "
        "AND source_admission.decision='in_scope' ORDER BY p.source_id",
        (seed.manifest["source_allowlist"],),
    )
    sources = cur.fetchall()
    result.dates = []
    owners = {}
    for sid, bid, names, reviewed, admitted in sources:
        value, basis = _date(names, reviewed, admitted)
        result.dates.append({"source_id": sid, "date": value, "basis": basis, "names": names})
        owners[bid] = sid
    result.manifest["source_allowlist"] = [d["source_id"] for d in result.dates]
    # The seed cutoff is a corpus freeze date, not a permanent product date cap.
    result.manifest["cutoff"] = date.today().isoformat()
    result.units = _units(cur, list(owners))
    cur.execute(
        "SELECT build_id,chunk_id,kind,title_text,section_path,unit_refs,context_refs,search_text "
        "FROM corpus.corpus_chunks WHERE build_id=ANY(%s::text[]) ORDER BY build_id,chunk_id",
        (list(owners),),
    )
    result.chunks = []
    by_build = {bid: {uid: u for (b, uid), u in result.units.items() if b == bid} for bid in owners}
    for bid, cid, kind, title, section, refs, context, text in cur.fetchall():
        c = project(
            {
                "source_id": owners[bid],
                "build_id": bid,
                "chunk_id": cid,
                "kind": kind,
                "title_text": title,
                "section_path": section,
                "unit_refs": refs,
                "context_refs": context,
                "search_text": text,
            },
            by_build[bid],
        )
        if c:
            result.chunks.append(c)
    result.vectors = dict(seed.vectors)
    cur.execute(
        "SELECT input_hash,embedding::text FROM corpus_retrieval.embeddings "
        "WHERE profile=%s AND status='ready' AND dimensions=%s",
        (seed.manifest["profile"], seed.manifest["dimensions"]),
    )
    for h, vector in cur.fetchall():
        result.vectors[h] = {
            "vector": validate_vector(json.loads(vector), seed.manifest["dimensions"])
        }
    result.index_id = text_hash(
        json.dumps(
            {
                "seed": seed.index_id,
                "manifest": result.manifest,
                "dates": result.dates,
                "chunks": [(c["build_id"], c["chunk_id"], c["input_hash"]) for c in result.chunks],
            },
            sort_keys=True,
        )
    )
    return result


def refresh(dsn: str, target: str, seed: NativeIndex) -> NativeIndex:
    check_native_target(target)
    if target != seed.target:
        raise ValueError("native_refresh_target_mismatch")
    with psycopg.connect(dsn, autocommit=True) as conn:
        read_pg._check_target(conn, target)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return refresh_on(cur, seed)


def _digest(text: str, slices: list[dict[str, Any]]) -> str:
    return text_hash(
        json.dumps({"text": text, "slices": slices}, ensure_ascii=False, sort_keys=True)
    )


def locator_for(chunk_id: str, text: str, slices: list[dict[str, Any]]) -> str:
    return PREFIX + quote(chunk_id, safe="") + "/" + _digest(text, slices)


def search(
    dsn: str, target: str, query: str, limit: int, trace: Any = None
) -> tuple[list[Any], dict[str, object]]:
    from plugins.corpus.service import SearchHit, context_scope_id

    seed = configured_seed(target)
    index = refresh(dsn, target, seed)
    # The HTTP search contract accepts up to 50 sources. Native retrieval still
    # selects at most 20 blocks; a larger source limit cannot expand that budget.
    if not 1 <= limit <= 50:
        raise ValueError("native_hit_limit_invalid")
    result = search_native(dsn, target, query, index, limit=20, trace=trace, allow_fallback=True)
    chunks = {(c["build_id"], c["chunk_id"]): c for c in index.chunks}
    hits = []
    groups: dict[str, list[Any]] = {}
    for b in result.blocks:
        if b.build_id not in groups and len(groups) == limit:
            continue
        groups.setdefault(b.build_id, []).append(b)
    for blocks in groups.values():
        b = blocks[0]
        c = chunks[b.build_id, b.chunk_id]
        locators = tuple(
            locator_for(x.chunk_id, x.text, [asdict(s) for s in x.slices]) for x in blocks
        )
        locator = locators[0]
        counts: dict[str, int] = {}
        for x in blocks:
            kind = chunks[x.build_id, x.chunk_id]["kind"]
            counts[kind] = counts.get(kind, 0) + 1
        hits.append(
            SearchHit(
                doc_id=read_pg.build_handle(b.build_id),
                locator=locator,
                title=c["title_text"] or "",
                snippet="…" + b.text[:240] + "…",
                score=0.0,
                published=b.published or "",
                source_id=b.source_id,
                build_id=b.build_id,
                chunk_id=b.chunk_id,
                context_locators=locators,
                scope_id=context_scope_id(
                    b.build_id, [read_pg.parse_chunk_locator(loc) for loc in locators]
                ),
                context_by_kind=tuple(counts.items()),
            )
        )
    coverage: dict[str, object] = {
        "processing": "partial",
        "availability": "unknown",
        "query_status": "matched" if hits else "no_match",
        "retrieval_mode": result.retrieval_mode,
        "fallback_reason": result.fallback_reason,
        "native": {
            "policy": "native1",
            "index_id": result.index_id,
            "sources": len(index.dates),
            "chunks": len(index.chunks),
            "ready_vectors": sum(c["input_hash"] in index.vectors for c in index.chunks),
            "body_characters": sum(len(b.text) for bs in groups.values() for b in bs),
            "char_budget": result.char_budget,
            "hit_limit": limit,
            "block_limit": result.block_limit,
            "cutoff": result.cutoff,
            "unknown_date_sources": list(result.unknown_date_sources),
        },
        "reason_codes": [
            "native_prose_scope",
            *([result.fallback_reason] if result.fallback_reason else []),
        ],
    }
    return hits, coverage


def fetch(dsn: str, target: str | None, doc_id: str, locator: str) -> read_pg.ChunkEvidence:
    """Reconstruct a version-bound projection even after the trial switch is off."""
    check_native_target(target)
    bid = read_pg.parse_build_handle(doc_id)
    try:
        encoded, expected = locator[len(PREFIX) :].rsplit("/", 1)
        cid = unquote(encoded)
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or not cid:
            raise ValueError
    except ValueError as exc:
        raise read_pg.UnknownHandleError("native_locator_invalid") from exc
    with psycopg.connect(dsn, autocommit=True) as conn:
        read_pg._check_target(conn, target)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute(
                "SELECT b.source_id,c.kind,c.title_text,c.section_path,c.unit_refs,c.context_refs,c.search_text,"
                "p.active_build_id,a.decision,sa.decision "
                "FROM corpus.corpus_chunks c JOIN corpus.corpus_builds b USING(build_id) "
                "JOIN corpus.corpus_sources s ON s.source_id=b.source_id "
                "LEFT JOIN corpus.corpus_publications p ON p.source_id=b.source_id "
                "LEFT JOIN corpus.corpus_admissions a ON a.decision_id=p.current_decision_id "
                "LEFT JOIN corpus.corpus_admissions sa ON sa.decision_id=s.current_decision_id "
                "WHERE c.build_id=%s AND c.chunk_id=%s",
                (bid, cid),
            )
            row = cur.fetchone()
            if row is None:
                raise read_pg.UnknownHandleError("native_chunk_not_found")
            sid, kind, title, section, refs, context, text, active, decision, source_decision = row
            if decision != "in_scope" or source_decision != "in_scope":
                raise read_pg.WithdrawnError("native_source_withdrawn")
            units = {uid: u for (b, uid), u in _units(cur, [bid]).items()}
            c = project(
                {"unit_refs": refs, "context_refs": context, "kind": kind, "search_text": text},
                units,
            )
            if c is None:
                raise read_pg.IntegrityError("native_projection_unavailable")
            slices = raw_slices(c["search_text"], [units[uid] for uid in c["unit_refs"]])
            body = "\n".join(s.text for s in slices)
            raw_spans = [{k: v for k, v in asdict(s).items() if k != "text"} for s in slices]
            if _digest(body, raw_spans) != expected:
                raise read_pg.IntegrityError("native_projection_hash_changed")
            spans = []
            offset = 0
            for s in slices:
                spans.append((s.unit_id, offset, offset + len(s.text)))
                offset += len(s.text) + 1
            verified = tuple(
                read_pg.verified_unit(
                    bid,
                    uid,
                    units[uid]["raw_text"],
                    units[uid]["location"],
                    units[uid]["content_hash"],
                )
                for uid in dict.fromkeys(s.unit_id for s in slices)
            )
            return read_pg.ChunkEvidence(
                sid,
                bid,
                cid,
                kind,
                title,
                tuple(section),
                verified,
                body,
                (),
                tuple(spans),
                active == bid,
                native_slices=tuple(raw_spans),
            )
