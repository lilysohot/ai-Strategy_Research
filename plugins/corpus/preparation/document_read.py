"""Ordered, version-bound reading of authoritative units, independent of search chunks."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote

from plugins.corpus.preparation import read_pg

UNIT_PREFIX = "chunk:document1/"


@dataclass(frozen=True)
class DocumentUnit:
    unit: read_pg.UnitEvidence
    kind: str
    status: str


@dataclass(frozen=True)
class DocumentUnits:
    source_id: str
    build_id: str
    active: bool
    units: tuple[DocumentUnit, ...]


def unit_locator(unit_id: str) -> str:
    """An explicit authoritative-unit handle; never a guessed search chunk."""
    return UNIT_PREFIX + quote(unit_id, safe="")


def read_units(
    dsn: str,
    doc_id: str,
    *,
    sandbox_db: str | None = None,
    unit_id: str | None = None,
) -> DocumentUnits:
    """Read all units in source order, or one unit for citation verification.

    Search eligibility, top-k, overlapping chunk projections and active-build
    replacement cannot change this set. Admission and hashes are rechecked on
    every call in one read-only snapshot, including continuation requests.
    """
    import psycopg

    build_id = read_pg.parse_build_handle(doc_id)
    with psycopg.connect(dsn, autocommit=True) as conn:
        read_pg._check_target(conn, sandbox_db)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute(
                "SELECT b.source_id, p.active_build_id, sa.decision, pa.decision "
                "FROM corpus.corpus_builds b "
                "JOIN corpus.corpus_sources s ON s.source_id=b.source_id "
                "LEFT JOIN corpus.corpus_publications p ON p.source_id=b.source_id "
                "LEFT JOIN corpus.corpus_admissions sa ON sa.decision_id=s.current_decision_id "
                "LEFT JOIN corpus.corpus_admissions pa ON pa.decision_id=p.current_decision_id "
                "WHERE b.build_id=%s",
                (build_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise read_pg.UnknownHandleError("document_build_not_found")
            source_id, active_build, source_decision, publication_decision = row
            if source_decision != "in_scope" or publication_decision != "in_scope":
                raise read_pg.WithdrawnError("document_source_withdrawn")
            sql = (
                "SELECT unit_id, raw_text, location, content_hash, kind, status "
                "FROM corpus.corpus_units WHERE build_id=%s"
            )
            params = (build_id,)
            if unit_id is not None:
                sql += " AND unit_id=%s"
                params = (build_id, unit_id)
            cur.execute(sql + " ORDER BY ordinal NULLS LAST, unit_id", params)
            rows = cur.fetchall()
    if unit_id is not None and not rows:
        raise read_pg.UnknownHandleError("document_unit_not_found")
    units = tuple(
        DocumentUnit(
            read_pg.verified_unit(build_id, uid, raw or "", location, digest),
            str(kind),
            str(status),
        )
        for uid, raw, location, digest, kind, status in rows
    )
    return DocumentUnits(str(source_id), build_id, active_build == build_id, units)


def fetch_unit(
    dsn: str, doc_id: str, locator: str, *, sandbox_db: str | None = None
) -> read_pg.ChunkEvidence:
    """Resolve document-reading citations through the same authoritative read boundary."""
    unit_id = unquote(locator[len(UNIT_PREFIX) :])
    if not unit_id or unit_locator(unit_id) != locator:
        raise read_pg.UnknownHandleError("document_unit_locator_invalid")
    document = read_units(dsn, doc_id, sandbox_db=sandbox_db, unit_id=unit_id)
    item = document.units[0]
    unit = item.unit
    return read_pg.ChunkEvidence(
        source_id=document.source_id,
        build_id=document.build_id,
        chunk_id=locator.removeprefix("chunk:"),
        kind=item.kind,
        title_text=None,
        section_path=(),
        units=(unit,),
        text=unit.raw_text,
        source_ranges=((0, len(unit.raw_text)),),
        spans=((unit.unit_id, 0, len(unit.raw_text)),),
        active=document.active,
    )
