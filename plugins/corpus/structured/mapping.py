"""Lossless conversion from role packet offsets to authoritative unit coordinates.

Packet spans are an internal concatenation map, never external evidence offsets.
The returned handles use raw unit text, matching preparation.read_pg.UnitEvidence.
No substring search, nearest-unit lookup, database access or text normalization.
"""

from __future__ import annotations

from dataclasses import dataclass

from plugins.corpus.evidence import EvidencePacket
from plugins.corpus.structured.snapshot import (
    COORDINATE_SYSTEM,
    EvidenceSnapshot,
    SnapshotIntegrityError,
    SnapshotUnit,
    source_unit_id,
)


@dataclass(frozen=True)
class EvidenceReference:
    """Exact source-unit citation produced from a verified snapshot coordinate."""

    doc_id: str
    chunk_id: str
    unit_id: str
    locator: str
    text_sha256: str
    start: int
    end: int
    quote: str
    coordinate_system: str = COORDINATE_SYSTEM


def _reference(
    snapshot: EvidenceSnapshot, unit: SnapshotUnit, start: int, end: int
) -> EvidenceReference:
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(unit.text):
        raise SnapshotIntegrityError("evidence interval outside exact unit text")
    return EvidenceReference(
        doc_id=f"cv2:{snapshot.build_id}",
        chunk_id=unit.chunk_id,
        unit_id=source_unit_id(unit),
        locator=unit.locator,
        text_sha256=unit.text_sha256,
        start=start,
        end=end,
        quote=unit.text[start:end],
    )


def _packet_units(snapshot: EvidenceSnapshot, packet: EvidencePacket) -> list[SnapshotUnit]:
    snapshot.verify_identity()
    by_id = {unit.unit_id: unit for unit in snapshot.units}
    units = []
    cursor = 0
    for index, span in enumerate(packet.spans):
        unit = by_id.get(span.locator)
        if unit is None:
            raise SnapshotIntegrityError("packet span lacks exact snapshot unit handle")
        if index:
            cursor += 1
        if (span.start, span.end, span.text) != (cursor, cursor + len(unit.text), unit.text):
            raise SnapshotIntegrityError("packet concatenation map is inconsistent")
        cursor += len(unit.text)
        units.append(unit)
    if not units or packet.text != "\n".join(unit.text for unit in units):
        raise SnapshotIntegrityError("packet text does not reproduce source units")
    if not any(unit.chunk_id == packet.locator for unit in units):
        raise SnapshotIntegrityError("packet chunk does not match source units")
    return units


def resolve_unit_span(
    snapshot: EvidenceSnapshot, snapshot_unit_id: str, start: int, end: int
) -> EvidenceReference:
    """Resolve an exact frozen unit handle; source-unit names alone are insufficient."""
    snapshot.verify_identity()
    for unit in snapshot.units:
        if unit.unit_id == snapshot_unit_id:
            return _reference(snapshot, unit, start, end)
    raise SnapshotIntegrityError("unit handle does not belong to snapshot")


def resolve_packet_span(
    snapshot: EvidenceSnapshot, packet: EvidencePacket, start: int, end: int
) -> tuple[EvidenceReference, ...]:
    """Map a packet interval to ordered exact source fragments, excluding join separators."""
    units = _packet_units(snapshot, packet)
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(packet.text):
        raise SnapshotIntegrityError("evidence interval outside packet")
    result = []
    for unit, span in zip(units, packet.spans, strict=True):
        assert span.start is not None and span.end is not None
        left, right = max(start, span.start), min(end, span.end)
        if left < right:
            result.append(_reference(snapshot, unit, left - span.start, right - span.start))
    if not result:
        raise SnapshotIntegrityError("packet interval contains only synthetic separators")
    return tuple(result)


def resolve_cell_span(
    snapshot: EvidenceSnapshot, packet: EvidencePacket, cell_index: int
) -> EvidenceReference:
    """Use the explicit cell ordinal and unit provenance, including identical repeated cells."""
    units = _packet_units(snapshot, packet)
    if not 0 <= cell_index < len(packet.cells):
        raise SnapshotIntegrityError("cell index outside packet")
    cell = packet.cells[cell_index]
    matches = [unit for unit in units if unit.unit_id == cell.span.locator]
    if len(matches) != 1 or cell.span.start is None or cell.span.end is None:
        raise SnapshotIntegrityError("cell lacks an exact source unit interval")
    reference = _reference(snapshot, matches[0], cell.span.start, cell.span.end)
    if reference.quote != cell.value:
        raise SnapshotIntegrityError("cell quote does not reproduce exact source interval")
    return reference
