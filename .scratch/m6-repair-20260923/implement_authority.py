from pathlib import Path
r=Path('/home/administrator/FrontierAgent')
p=r/'plugins/corpus/preparation/read_pg.py';s=p.read_text()
s=s.replace('from dataclasses import dataclass','from dataclasses import dataclass, replace')
s=s.replace('_SANDBOX_DB = "i2_sandbox_corpus"','_SANDBOX_DB = "i2_sandbox_corpus"\nAUTHORITY_REV = "authority-context-2"',1)
s=s.replace('    active: bool\n\n\n@dataclass', '    active: bool\n    #: Explicit contextual units; source_ranges still describes the original chunk only.\n    context_unit_ids: tuple[str, ...] = ()\n\n\n@dataclass',1)
a=s.index('def fetch_verbatim(');b=s.index('\n\n_DOC_SQL',a)
s=s[:a]+'''def verified_unit(
    build_id: str, unit_id: str, raw_text: str, location: object, content_hash: str
) -> UnitEvidence:
    """Validate every authoritative unit before exposing its text or coordinates."""
    if sha256_of_bytes(raw_text.encode()) != content_hash:
        raise IntegrityError(f"权威单元内容哈希不符（疑似篡改）: {unit_id} @ {build_id[:12]}…")
    loc = location if isinstance(location, dict) else {}
    return UnitEvidence(
        unit_id=unit_id,
        raw_text=raw_text,
        page=loc.get("page"),
        element=loc.get("element"),
        cells=tuple(tuple(int(v) for v in cell) for cell in (loc.get("cells") or ())),
    )


def with_units(
    evidence: ChunkEvidence,
    units: tuple[UnitEvidence, ...],
    *,
    context_unit_ids: tuple[str, ...] = (),
) -> ChunkEvidence:
    """Assemble text and offsets together, including empty units and context provenance."""
    spans: list[tuple[str, int, int]] = []
    offset = 0
    for index, unit in enumerate(units):
        if index:
            offset += 1
        spans.append((unit.unit_id, offset, offset + len(unit.raw_text)))
        offset += len(unit.raw_text)
    return replace(
        evidence, units=units, text="\\n".join(u.raw_text for u in units),
        spans=tuple(spans), context_unit_ids=context_unit_ids,
    )


def fetch_verbatim(
    dsn: str,
    doc_id: str,
    locator: str,
    *,
    sandbox_db: str = _SANDBOX_DB,
) -> ChunkEvidence:
    """Fetch the versioned chunk and verified context within one read snapshot.

    Context is the same bounded structural projection used by fetch_bands. The
    original chunk ranges remain unchanged; added units are explicitly identified.
    """
    import psycopg

    from plugins.corpus.preparation.cross_boundary import aggregate_band_chunks_on

    build_id = parse_build_handle(doc_id)
    chunk_id = parse_chunk_locator(locator)
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute(_CHUNK_SQL, {"build_id": build_id, "chunk_id": chunk_id})
            row = cur.fetchone()
            if row is None:
                raise UnknownHandleError(f"句柄不存在或跨 build：({build_id[:12]}…, {chunk_id})")
            unit_ids = list(row[5] or ())
            unit_rows = []
            if unit_ids:
                cur.execute(_UNITS_SQL, {"build_id": build_id, "unit_ids": unit_ids})
                unit_rows = [(build_id, *u, None) for u in cur.fetchall()]
            evidence = _assemble_chunk_evidence(build_id, chunk_id, row, unit_rows)
            return aggregate_band_chunks_on(cur, (evidence,))[0]
''' + s[b:]
a=s.index('def _assemble_chunk_evidence(')
s=s[:a]+'''def _assemble_chunk_evidence(
    build_id: str,
    chunk_id: str,
    chunk_row: tuple,
    unit_rows: list[tuple],
) -> ChunkEvidence:
    """The common integrity gate for individual and batched chunk reads."""
    decision = chunk_row[10]
    if decision and decision != "in_scope":
        raise WithdrawnError(f"来源当前准入为 {decision!r}，活动版本已撤下，不得继续服务该句柄")
    units = tuple(
        verified_unit(build_id, str(uid), str(raw or ""), loc, str(digest or ""))
        for _bid, uid, raw, loc, digest, _ordinal in unit_rows
    )
    missing = set(chunk_row[5] or ()) - {u.unit_id for u in units}
    if missing:
        raise IntegrityError(f"chunk 引用了不存在的单元: {sorted(missing)} @ {build_id[:12]}…")
    evidence = ChunkEvidence(
        source_id=str(chunk_row[7]), build_id=build_id, chunk_id=chunk_id,
        kind=str(chunk_row[2] or ""), title_text=chunk_row[3],
        section_path=tuple(chunk_row[4] or ()), units=(), text="",
        source_ranges=tuple((int(span[0]), int(span[1])) for span in (chunk_row[6] or ())),
        spans=(), active=bool(chunk_row[9]),
    )
    return with_units(evidence, units)
'''
# Keep batched assembly + context inside the same repeatable-read cursor.
a=s.index('def fetch_bands(');tail=s[a:]
tail=tail.replace('    import psycopg\n','    import psycopg\n\n    from plugins.corpus.preparation.cross_boundary import aggregate_band_chunks_on\n',1)
tail=tail.replace('        with conn.cursor() as cur:\n            cur.execute(','        with conn.transaction(), conn.cursor() as cur:\n            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")\n            cur.execute(',1)
x=tail.index('    by_key = {');y=tail.index('\n\ndef _assemble_chunk_evidence',x)
block=tail[x:y].replace('    return tuple(out)','    return aggregate_band_chunks_on(cur, tuple(out))')
tail=tail[:x]+''.join('        '+line if line.strip() else line for line in block.splitlines(keepends=True))+tail[y:]
s=s[:a]+tail;p.write_text(s)

p=r/'plugins/corpus/preparation/cross_boundary.py';s=p.read_text()
s=s.replace('if TYPE_CHECKING:\n    pass','if TYPE_CHECKING:\n    import psycopg')
s=s.replace('    UnitEvidence,\n','    UnitEvidence,\n    verified_unit,\n    with_units,\n')
a=s.index('def _unit_evidence(');b=s.index('def aggregate_band_chunks(',a);s=s[:a]+s[b:]
a=s.index('    # 需要 bbox');b=s.index('    frag_map =',a)
old=s[a:b]
# Retain pure data mapping, moving query to caller-owned cursor.
x=old.index('            cur.execute(');query=old[x:]
query=''.join(line[8:] if line.startswith('        ') else line for line in query.splitlines(keepends=True))
preamble=old[:old.index('    with psycopg.connect')]
wrapper='''    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, sandbox_db)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return aggregate_band_chunks_on(
                cur, chunk_evs, stitch_continuation=stitch_continuation,
                attach_source_note=attach_source_note,
            )


def aggregate_band_chunks_on(
    cur: psycopg.Cursor,
    chunk_evs: tuple[ChunkEvidence, ...],
    *,
    stitch_continuation: bool = True,
    attach_source_note: bool = True,
) -> tuple[ChunkEvidence, ...]:
    """Read bounded context in the same transaction as its chunk and authorization."""
    if not chunk_evs:
        return chunk_evs
'''
s=s[:a]+wrapper+preamble+query+s[b:]
s=s.replace('(ordinal if ordinal is not None else -1, nid, _unit_evidence(nid, raw, nloc))','(ordinal if ordinal is not None else -1, nid,\n             verified_unit(ev.build_id, nid, raw, nloc, str(rec[3]) if rec else ""))')
a=s.index('    units_out =');s=s[:a]+'''    units_out = tuple(ue for *_a, ue in merged_units)
    context_ids = tuple(dict.fromkeys((*ev.context_unit_ids, *(uid for uid, _, _ in merges))))
    return with_units(ev, units_out, context_unit_ids=context_ids)
'''
p.write_text(s)

p=r/'plugins/corpus/service.py';s=p.read_text();s=s.replace('from plugins.corpus.preparation import cross_boundary, read_pg','from plugins.corpus.preparation import read_pg');s=s.replace('        chunk_evs = cross_boundary.aggregate_band_chunks(\n            self._dsn, chunk_evs, sandbox_db=_I2_SANDBOX_DB\n        )  # F4 跨 NOISE/kept 边界联合取证\n','');p.write_text(s)
p=r/'plugins/tools/corpus_fetch.py';s=p.read_text();s=s.replace('from plugins.corpus.service import get_service','from plugins.corpus.preparation.read_pg import AUTHORITY_REV\nfrom plugins.corpus.service import get_service');s=s.replace('            "units": [','            "authority_rev": AUTHORITY_REV,\n            "context_unit_ids": list(evidence.context_unit_ids),\n            "units": [');s=s.replace('不做摘要、不做改写、不做拼接。**任何加工都会让「逐字」这一性质失效**，','不做摘要、不做改写；结构性上下文以明确单元标识附带，逐单元哈希验证，\n单元间以换行分隔，spans 保留各单元精确范围。');p.write_text(s)
