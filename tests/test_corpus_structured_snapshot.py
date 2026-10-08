from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

from plugins.corpus.evidence_pipeline import (
    build_evidence_run_from_snapshot,
    evidence_document_from_snapshot,
)
from plugins.corpus.material_semantics import extract_material_understanding_from_snapshot
from plugins.corpus.service import CorpusService
from plugins.corpus.structured.mapping import resolve_cell_span, resolve_packet_span
from plugins.corpus.structured.snapshot import (
    EvidenceSnapshot,
    SnapshotBuildSource,
    SnapshotCellSource,
    SnapshotChangedError,
    SnapshotDependencySource,
    SnapshotDocumentSource,
    SnapshotGapSource,
    SnapshotHead,
    SnapshotIntegrityError,
    SnapshotReader,
    SnapshotTextSource,
    SnapshotUnitSource,
    build_snapshot,
    select_snapshot,
    source_unit_id,
)

SOURCE_ID = "a" * 64
BUILD_ID = "b" * 64
NEXT_BUILD_ID = "c" * 64
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "corpus_structured_snapshot"


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("snapshot tests must not access network, models or databases")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(CorpusService, "_connect", denied)
    monkeypatch.setattr("plugins.corpus.service.build_default_llm", denied)


class MemoryReader(SnapshotReader):
    def __init__(
        self,
        payload: SnapshotBuildSource,
        *,
        next_head: SnapshotHead | None = None,
    ) -> None:
        self.payload = payload
        self.next_head = next_head
        self.head_reads = 0

    def read_head(self, source_id: str) -> SnapshotHead:
        assert source_id == SOURCE_ID
        self.head_reads += 1
        if self.next_head is not None and self.head_reads > 1:
            return self.next_head
        return self.payload.head

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        assert head == self.payload.head
        return self.payload


def _payload(*, units: tuple[SnapshotUnitSource, ...] | None = None) -> SnapshotBuildSource:
    data = json.loads((FIXTURE_ROOT / "source.json").read_text(encoding="utf-8"))
    raw_head = data["head"]
    head = SnapshotHead(
        source_id=raw_head["source_id"],
        build_id=raw_head["build_id"],
        publication_generation=raw_head["publication_generation"],
    )
    fixture_units: list[SnapshotUnitSource] = []
    for raw_unit in data["units"]:
        dependencies = tuple(
            SnapshotDependencySource(
                kind=dependency["kind"],
                target_unit_id=dependency.get("target_unit_id"),
                status=dependency.get("status", "present"),
                target_chunk_id=dependency.get("target_chunk_id"),
                required_for=tuple(dependency.get("required_for", ("cite",))),
                reason=dependency.get("reason"),
            )
            for dependency in raw_unit.get("dependencies", ())
        )
        cells = tuple(SnapshotCellSource(**cell) for cell in raw_unit.get("cells", ()))
        fixture_units.append(
            SnapshotUnitSource(
                source_unit_id=raw_unit["source_unit_id"],
                chunk_id=raw_unit["chunk_id"],
                kind=raw_unit["kind"],
                text=raw_unit["text"],
                locator=raw_unit["locator"],
                page=raw_unit.get("page"),
                ordinal=raw_unit.get("ordinal"),
                cells=cells,
                dependencies=dependencies,
            )
        )
    raw_document = data["document"]
    return SnapshotBuildSource(
        head=head,
        parser_versions=data["parser_versions"],
        document=SnapshotDocumentSource(
            title=raw_document["title"],
            subject=raw_document["subject"],
            published=raw_document["published"],
        ),
        units=units or tuple(fixture_units),
        gaps=tuple(
            SnapshotGapSource(
                code=gap["code"],
                locator=gap["locator"],
                context_status=gap["context_status"],
            )
            for gap in data["gaps"]
        ),
    )


def _snapshot(payload: SnapshotBuildSource | None = None) -> EvidenceSnapshot:
    return build_snapshot(MemoryReader(payload or _payload()), SOURCE_ID)


def test_snapshot_fixture_manifest_binds_synthetic_source_bytes() -> None:
    manifest = json.loads((FIXTURE_ROOT / "asset-manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic_only"] is True
    assert manifest["real_source_ids"] == []
    for asset in manifest["assets"]:
        path = FIXTURE_ROOT / asset["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]


def test_snapshot_is_immutable_content_addressed_and_bound_to_build() -> None:
    snapshot = _snapshot()
    snapshot.verify_identity()

    assert snapshot.source_id == SOURCE_ID
    assert snapshot.build_id == BUILD_ID
    assert snapshot.source_id != snapshot.build_id
    assert snapshot.publication_generation == 3
    assert snapshot.parser_versions["snapshot"] == "structured-snapshot-2"
    assert snapshot.snapshot_id.startswith("sha256:")
    assert all(unit.span.end == len(unit.text) for unit in snapshot.units)

    document = evidence_document_from_snapshot(snapshot, role="claims")
    assert document.doc_id == f"cv2:{BUILD_ID}"
    assert document.source_path == f"cv2:{BUILD_ID}"
    assert document.source_rev == snapshot.snapshot_id
    assert all(packet.locator.startswith("chunk:") for packet in document.packets)


def test_publication_switch_fails_before_exposing_a_mixed_snapshot() -> None:
    payload = _payload()
    reader = MemoryReader(
        payload,
        next_head=SnapshotHead(
            source_id=SOURCE_ID,
            build_id=NEXT_BUILD_ID,
            publication_generation=4,
        ),
    )
    with pytest.raises(SnapshotChangedError, match="changed"):
        build_snapshot(reader, SOURCE_ID)


def test_same_text_with_changed_position_or_kind_changes_snapshot_identity() -> None:
    original = _payload()
    base = _snapshot(original)
    moved_units = list(original.units)
    moved_units[1] = replace(
        moved_units[1],
        kind="heading",
        locator="page:9/heading:2",
    )
    moved = _snapshot(replace(original, units=tuple(moved_units)))

    assert base.units[1].text == moved.units[1].text
    assert base.snapshot_id != moved.snapshot_id
    assert base.units[1].unit_id != moved.units[1].unit_id


def test_claims_and_material_select_independently_from_one_snapshot() -> None:
    snapshot = _snapshot()
    claims = select_snapshot(snapshot, "claims")
    material = select_snapshot(snapshot, "material_items")

    assert claims.snapshot_id == material.snapshot_id == snapshot.snapshot_id
    assert {unit.kind for unit in claims.units} >= {"prose", "table", "table_note"}
    assert "heading" not in {unit.kind for unit in claims.units}
    assert "heading" in {unit.kind for unit in material.units}

    claims_run = build_evidence_run_from_snapshot(snapshot, max_prose_calls=0)
    material_run = extract_material_understanding_from_snapshot(
        snapshot,
        llm=None,
        max_calls=0,
        extract_relations=False,
    )
    assert claims_run.document.parse_rev == snapshot.snapshot_id
    assert material_run.evidence_run_id != claims_run.run_id
    assert material_run.understanding.source.source_rev == snapshot.snapshot_id


def test_table_cells_reach_claims_and_notes_reach_material_as_prose() -> None:
    snapshot = _snapshot()
    claims_document = evidence_document_from_snapshot(snapshot, role="claims")
    table_packet = next(packet for packet in claims_document.packets if packet.kind == "table")
    assert table_packet.locator == "chunk:table-chunk"
    assert table_packet.cells[0].row == "营业收入"
    assert table_packet.cells[0].column == "2025A"
    assert (
        table_packet.text[table_packet.cells[0].span.start : table_packet.cells[0].span.end]
        == "100"
    )
    assert table_packet.context == ("脚注：2025A 为虚构实际值，单位为亿元。",)

    run = build_evidence_run_from_snapshot(snapshot, max_prose_calls=0)
    table_result = next(
        item for item in run.packet_runs if item.packet_id == table_packet.packet_id
    )
    # This historical synthetic fixture supplied label strings but no label intervals.
    assert table_result.status == "unknown"
    assert table_result.records == 0
    assert "context_missing" in table_result.reasons

    material_document = evidence_document_from_snapshot(snapshot, role="material_items")
    note_packet = next(
        packet for packet in material_document.packets if packet.text.startswith("脚注：")
    )
    assert note_packet.kind == "prose"
    assert note_packet.locator == "chunk:table-chunk"


def test_explicit_cross_packet_condition_is_bound_and_missing_condition_degrades() -> None:
    snapshot = _snapshot()
    forecast = next(unit for unit in snapshot.units if source_unit_id(unit) == "forecast-u")
    condition = next(unit for unit in snapshot.units if source_unit_id(unit) == "condition-u")
    assert forecast.dependencies == (condition.unit_id,)
    assert forecast.metadata["context_status"] == "complete"

    payload = _payload()
    broken_units = tuple(
        replace(
            unit,
            dependencies=(
                SnapshotDependencySource(
                    kind="condition",
                    target_unit_id="missing-condition",
                    required_for=("cite", "compare", "calculate"),
                ),
            ),
        )
        if unit.source_unit_id == "forecast-u"
        else unit
        for unit in payload.units
    )
    broken = _snapshot(replace(payload, units=broken_units))
    broken_forecast = next(unit for unit in broken.units if source_unit_id(unit) == "forecast-u")
    assert broken_forecast.metadata["context_status"] == "missing"
    assert any(gap.code == "dependency_condition_missing" for gap in broken.gaps)
    document = evidence_document_from_snapshot(broken, role="claims")
    packet = next(packet for packet in document.packets if "20亿元" in packet.text)
    assert packet.status == "partial"
    assert packet.reasons == ("context_missing",)


@pytest.mark.parametrize("status", ["ambiguous", "budget_exceeded"])
def test_declared_dependency_uncertainty_is_preserved(
    status: Literal["ambiguous", "budget_exceeded"],
) -> None:
    payload = _payload()
    changed_units = tuple(
        replace(
            unit,
            dependencies=(
                SnapshotDependencySource(
                    kind="condition",
                    target_unit_id=None,
                    status=status,
                    required_for=("cite", "compare", "calculate"),
                ),
            ),
        )
        if unit.source_unit_id == "forecast-u"
        else unit
        for unit in payload.units
    )
    snapshot = _snapshot(replace(payload, units=changed_units))
    forecast = next(unit for unit in snapshot.units if source_unit_id(unit) == "forecast-u")
    assert forecast.metadata["context_status"] == status
    assert any(gap.code == f"dependency_condition_{status}" for gap in snapshot.gaps)
    document = evidence_document_from_snapshot(snapshot, role="claims")
    packet = next(packet for packet in document.packets if "20亿元" in packet.text)
    assert packet.status == "partial"
    assert packet.reasons == (f"context_{status}",)


def test_continued_table_keeps_each_cell_on_its_exact_source_unit() -> None:
    payload = _payload()
    first = SnapshotUnitSource(
        source_unit_id="continued-p1",
        chunk_id="continued-table",
        kind="table_row",
        text="营业收入\n100",
        locator="page:1/table:1/row:1",
        page=1,
        ordinal=1,
        cells=(
            SnapshotCellSource(
                row="营业收入",
                column="2025A",
                value="100",
                unit="亿元",
                start=5,
                end=8,
            ),
        ),
    )
    second = SnapshotUnitSource(
        source_unit_id="continued-p2",
        chunk_id="continued-table",
        kind="table_row",
        text="营业收入\n120",
        locator="page:2/table:1/row:1",
        page=2,
        ordinal=2,
        cells=(
            SnapshotCellSource(
                row="营业收入",
                column="2026E",
                value="120",
                unit="亿元",
                start=5,
                end=8,
            ),
        ),
    )
    snapshot = _snapshot(replace(payload, units=(first, second)))
    document = evidence_document_from_snapshot(snapshot, role="claims")
    packet = document.packets[0]

    assert packet.kind == "table"
    assert [cell.column for cell in packet.cells] == ["2025A", "2026E"]
    assert [resolve_cell_span(snapshot, packet, i).locator for i in range(2)] == [
        "page:1/table:1/row:1",
        "page:2/table:1/row:1",
    ]
    assert [
        unit.text[cell.span.start : cell.span.end]
        for unit, cell in zip((first, second), packet.cells, strict=True)
    ] == [
        "100",
        "120",
    ]


def test_duplicate_quotes_keep_distinct_chunk_and_unit_coordinates() -> None:
    snapshot = _snapshot()
    document = evidence_document_from_snapshot(snapshot, role="material_items")
    duplicates = [packet for packet in document.packets if packet.text == "风险可控。"]

    assert len(duplicates) == 2
    assert {packet.locator for packet in duplicates} == {
        "chunk:duplicate-a-chunk",
        "chunk:duplicate-b-chunk",
    }
    assert {
        resolve_packet_span(snapshot, packet, 0, len(packet.text))[0].unit_id
        for packet in duplicates
    } == {
        "duplicate-a",
        "duplicate-b",
    }


def test_cell_and_unit_intervals_are_rejected_instead_of_guessed() -> None:
    payload = _payload()
    invalid_units = list(payload.units)
    table = next(unit for unit in invalid_units if unit.source_unit_id == "table-u")
    bad_cell = replace(table.cells[0], start=0, end=3)
    invalid_units[invalid_units.index(table)] = replace(table, cells=(bad_cell,))
    with pytest.raises(SnapshotIntegrityError, match="does not reproduce"):
        _snapshot(replace(payload, units=tuple(invalid_units)))


def test_service_snapshot_entrypoints_do_not_open_a_database_or_reparse() -> None:
    snapshot = _snapshot()
    service = CorpusService("postgresql://unused")

    claims = service.extract_claims_from_snapshot(snapshot, max_prose_calls=0)
    material = service.understand_material_from_snapshot(
        snapshot,
        max_calls=0,
        extract_relations=False,
    )
    assert claims.document.doc_id == f"cv2:{BUILD_ID}"
    assert material.understanding.source.source_id == f"cv2:{BUILD_ID}"


def test_empty_source_unit_is_a_visible_gap_not_an_implicit_packet() -> None:
    payload = _payload(
        units=(
            SnapshotUnitSource(
                source_unit_id="empty",
                chunk_id="gap-chunk",
                kind="gap",
                text="",
                locator="page:1/image:1",
            ),
        )
    )
    with pytest.raises(SnapshotIntegrityError, match="represented as a gap"):
        _snapshot(payload)


def test_gap_changes_are_identity_changes_and_tampering_is_rejected() -> None:
    payload = _payload()
    snapshot = _snapshot(payload)
    assert snapshot.snapshot_id != _snapshot(replace(payload, gaps=())).snapshot_id
    tampered = EvidenceSnapshot.model_validate({**snapshot.model_dump(), "gaps": []})
    with pytest.raises(SnapshotIntegrityError):
        tampered.verify_identity()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chunk_id", ""),
        ("chunk_id", "chunk:"),
        ("chunk_id", "bad chunk"),
        ("chunk_id", "bad/chunk"),
        ("locator", ""),
    ],
)
def test_snapshot_rejects_schema_invalid_unit_handles(field: str, value: str) -> None:
    payload = _payload()
    unit = replace(payload.units[0], **{field: value})

    with pytest.raises(SnapshotIntegrityError, match=r"unit (chunk_id|locator)"):
        _snapshot(replace(payload, units=(unit,)))


@pytest.mark.parametrize("version", ["parse", "clean", "chunk"])
@pytest.mark.parametrize("mode", ["missing", "empty"])
def test_snapshot_requires_complete_pipeline_versions(version: str, mode: str) -> None:
    payload = _payload()
    versions = dict(payload.parser_versions)
    if mode == "missing":
        versions.pop(version)
    else:
        versions[version] = ""

    with pytest.raises(SnapshotIntegrityError, match="parser_versions"):
        _snapshot(replace(payload, parser_versions=versions))


@pytest.mark.parametrize(("field", "value"), [("code", ""), ("locator", "")])
def test_snapshot_rejects_schema_invalid_gap_fields(field: str, value: str) -> None:
    payload = _payload()
    gap = replace(payload.gaps[0], **{field: value})

    with pytest.raises(SnapshotIntegrityError, match="gap"):
        _snapshot(replace(payload, gaps=(gap,)))


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("chunk_id", "unit chunk_id"),
        ("locator", "unit locator"),
        ("parser_versions", "parser_versions"),
    ],
)
def test_verify_identity_rejects_deserialized_invalid_contract_fields(
    target: str, expected: str
) -> None:
    data = _snapshot().model_dump(mode="json")
    if target == "parser_versions":
        data["parser_versions"] = {"snapshot": "structured-snapshot-2"}
    else:
        data["units"][0][target] = "chunk:" if target == "chunk_id" else ""

    with pytest.raises(SnapshotIntegrityError, match=expected):
        EvidenceSnapshot.model_validate(data).verify_identity()


def test_serialized_dependency_removal_is_rejected() -> None:
    data = _snapshot().model_dump(mode="json")
    data["units"][1]["dependencies"] = []
    with pytest.raises(SnapshotIntegrityError):
        EvidenceSnapshot.model_validate(data).verify_identity()


def test_empty_source_unit_id_is_rejected_before_exposing_a_snapshot() -> None:
    payload = _payload()
    unit = replace(payload.units[0], source_unit_id="")
    with pytest.raises(SnapshotIntegrityError, match="source_unit_id"):
        _snapshot(replace(payload, units=(unit,)))


def test_deserialized_empty_source_unit_id_fails_at_identity_gate() -> None:
    data = _snapshot().model_dump(mode="json")
    data["units"][0]["metadata"]["source_unit_id"] = ""
    with pytest.raises(SnapshotIntegrityError, match="source_unit_id"):
        EvidenceSnapshot.model_validate(data).verify_identity()


def test_explicit_empty_dependency_chunk_does_not_fall_back_to_source_chunk() -> None:
    payload = _payload()
    target = replace(payload.units[0], source_unit_id="target", chunk_id="same")
    unit = replace(
        target,
        source_unit_id="dependent",
        dependencies=(
            SnapshotDependencySource(kind="condition", target_unit_id="target", target_chunk_id=""),
        ),
    )
    snapshot = _snapshot(replace(payload, units=(target, unit)))
    assert snapshot.units[1].metadata["context_status"] == "missing"
    assert snapshot.units[1].dependencies == ()


def test_explicit_wrong_chunk_is_not_repaired_by_unique_match() -> None:
    payload = _payload()
    units = list(payload.units)
    units[1] = replace(
        units[1],
        dependencies=(replace(units[1].dependencies[0], target_chunk_id="wrong"),),
    )
    snapshot = _snapshot(replace(payload, units=tuple(units)))
    assert snapshot.units[1].metadata["context_status"] == "missing"


@pytest.mark.parametrize("bad_status", ["missing", "ambiguous", "budget_exceeded"])
def test_transitive_dependency_status_reaches_both_role_packets(bad_status: str) -> None:
    payload = _payload()
    units = list(payload.units)
    units[2] = replace(
        units[2],
        dependencies=(
            SnapshotDependencySource(kind="condition", target_unit_id=None, status=bad_status),
        ),
    )
    snapshot = _snapshot(replace(payload, units=tuple(units)))
    for role in ("claims", "material_items"):
        document = evidence_document_from_snapshot(snapshot, role=role)
        packet = next(p for p in document.packets if p.locator == "chunk:forecast-chunk")
        assert packet.status == "partial"
        assert f"context_{bad_status}" in packet.reasons


@pytest.mark.parametrize("status", ["noise", "out_of_scope", "review_required", "needs_ocr"])
def test_cleaning_disposition_never_upgrades_to_available(status: str) -> None:
    payload = _payload()
    units = list(payload.units)
    units[2] = replace(units[2], status=status, reasons=("source_disposition",))
    snapshot = _snapshot(replace(payload, units=tuple(units)))
    for role in ("claims", "material_items"):
        document = evidence_document_from_snapshot(snapshot, role=role)
        assert all(
            p.status != "available"
            for p in document.packets
            if p.locator in {"chunk:forecast-chunk", "chunk:condition-chunk"}
        )


def test_material_never_executes_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("R2 must not execute Claims")

    monkeypatch.setattr("plugins.corpus.evidence_pipeline.extract_evidence", denied)
    extract_material_understanding_from_snapshot(_snapshot(), llm=None, max_calls=0)


@pytest.mark.parametrize("role", ["claims", "material_items"])
def test_positive_budget_requires_explicit_extraction_adapter(role: str) -> None:
    service = CorpusService("postgresql://unused")
    with pytest.raises(ValueError, match=r"explicit.*adapter"):
        if role == "claims":
            service.extract_claims_from_snapshot(_snapshot(), max_prose_calls=1)
        else:
            service.understand_material_from_snapshot(_snapshot(), max_calls=1)


def test_continued_cell_offsets_are_unit_local_for_unicode_sources() -> None:
    payload = _payload()
    for prefix in ("营业收入", "😀收入", "e\u0301收入", "营业\r\n收入"):
        text = prefix + "\n100"
        start = len(prefix) + 1
        units = tuple(
            SnapshotUnitSource(
                source_unit_id=f"row-{i}",
                chunk_id="continued",
                kind="table_row",
                text=text,
                locator=f"page:{i + 1}/row:1",
                cells=(
                    SnapshotCellSource(
                        row=prefix,
                        column="2025A",
                        value="100",
                        unit="亿元",
                        start=start,
                        end=start + 3,
                    ),
                ),
            )
            for i in range(3)
        )
        snapshot = _snapshot(replace(payload, units=units))
        packet = evidence_document_from_snapshot(snapshot, role="claims").packets[0]
        for cell in packet.cells:
            assert text[cell.span.start : cell.span.end] == cell.value


def _proven_table(unit_id: str = "row", chunk_id: str = "table") -> SnapshotUnitSource:
    return SnapshotUnitSource(
        source_unit_id=unit_id,
        chunk_id=chunk_id,
        kind="table_row",
        text="营业收入 2025A 100 亿元",
        locator="page:1/table:1/row:1",
        metadata={"table_consumption_status": "verified_complete"},
        cells=(
            SnapshotCellSource(
                row="营业收入",
                column="2025A",
                value="100",
                unit="亿元",
                start=11,
                end=14,
                row_ref=SnapshotTextSource(unit_id, chunk_id, 0, 4),
                column_ref=SnapshotTextSource(unit_id, chunk_id, 5, 10),
                unit_ref=SnapshotTextSource(unit_id, chunk_id, 15, 17),
            ),
        ),
    )


def test_unverified_table_is_auditable_but_blocked_from_downstream() -> None:
    source = replace(_proven_table(), metadata={})
    payload = _payload(units=(source,))
    snapshot = _snapshot(
        replace(
            payload,
            parser_versions={**payload.parser_versions, "parse": "reader-pdf-11+pymupdf-test"},
            document=replace(payload.document, subject="999999.SZ"),
        )
    )

    for role in ("claims", "material_items"):
        packet = evidence_document_from_snapshot(snapshot, role=role).packets[0]
        assert packet.kind == "table"
        assert packet.text == source.text
        assert packet.status == "partial"
        assert packet.reasons == ("table_untrusted_or_incomplete",)

    run = build_evidence_run_from_snapshot(snapshot)
    assert run.facts == ()
    assert run.packet_runs[0].status == "unknown"
    assert run.packet_runs[0].reasons == ("table_untrusted_or_incomplete",)

    material_run = extract_material_understanding_from_snapshot(
        snapshot,
        llm=None,
        max_calls=0,
        extract_relations=False,
    )
    assert material_run.understanding.items == ()
    assert material_run.packet_runs[0].status == "unknown"
    assert material_run.packet_runs[0].reasons == ("table_untrusted_or_incomplete",)


def test_unverified_table_dependency_does_not_leak_into_prose_context() -> None:
    table = replace(_proven_table(), metadata={})
    prose = SnapshotUnitSource(
        source_unit_id="prose",
        chunk_id="prose",
        kind="paragraph",
        text="正文结论。",
        locator="page:1/prose:1",
        dependencies=(
            SnapshotDependencySource(
                kind="condition",
                target_unit_id=table.source_unit_id,
                target_chunk_id=table.chunk_id,
            ),
        ),
    )
    payload = _payload(units=(table, prose))
    snapshot = _snapshot(
        replace(
            payload,
            parser_versions={**payload.parser_versions, "parse": "reader-pdf-11+pymupdf-test"},
        )
    )
    packet = next(
        item
        for item in evidence_document_from_snapshot(snapshot, role="material_items").packets
        if item.kind == "prose"
    )

    assert table.text not in packet.context
    assert packet.status == "partial"
    assert packet.reasons == ("table_untrusted_or_incomplete",)


def test_proven_table_remains_deterministic_and_every_cell_maps() -> None:
    source = _proven_table()
    payload = _payload(units=(source,))
    snapshot = _snapshot(replace(payload, document=replace(payload.document, subject="999999.SZ")))
    run = build_evidence_run_from_snapshot(snapshot)
    assert run.packet_runs[0].method == "deterministic-table"
    assert run.packet_runs[0].records == 1
    assert "calculate" in run.facts[0].usable_for
    reference = resolve_cell_span(snapshot, run.document.packets[0], 0)
    assert reference.doc_id == f"cv2:{BUILD_ID}"
    assert reference.unit_id == "row"
    assert reference.quote == source.text[reference.start : reference.end] == "100"


def test_external_header_uses_explicit_reference_not_neighbor_guess() -> None:
    row = _proven_table()
    header = SnapshotUnitSource(
        source_unit_id="header",
        chunk_id="headers",
        kind="heading",
        text="2025A",
        locator="page:1/header:1",
    )
    cell = replace(row.cells[0], column_ref=SnapshotTextSource("header", "headers", 0, 5))
    row = replace(row, cells=(cell,))
    snapshot = _snapshot(_payload(units=(header, row)))
    packet = next(
        p
        for p in evidence_document_from_snapshot(snapshot, role="claims").packets
        if p.kind == "table"
    )
    references = resolve_packet_span(snapshot, packet, 0, len(packet.text))
    assert [(ref.chunk_id, ref.unit_id) for ref in references] == [
        ("chunk:headers", "header"),
        ("chunk:table", "row"),
    ]
    assert packet.cells[0].column_span.start == 0
    assert packet.status == "available"
    bad_cell = replace(cell, column_ref=SnapshotTextSource("header", "headers", 1, 5))
    with pytest.raises(SnapshotIntegrityError, match="reference"):
        _snapshot(_payload(units=(header, replace(row, cells=(bad_cell,)))))


def test_repeated_source_unit_ids_and_quotes_map_by_exact_chunk() -> None:
    source = SnapshotUnitSource(
        source_unit_id="same",
        chunk_id="a",
        kind="prose",
        text="😀重复引文",
        locator="same-location",
    )
    snapshot = _snapshot(_payload(units=(source, replace(source, chunk_id="b"))))
    document = evidence_document_from_snapshot(snapshot, role="material_items")
    refs = [resolve_packet_span(snapshot, packet, 0, 2)[0] for packet in document.packets]
    assert [ref.chunk_id for ref in refs] == ["chunk:a", "chunk:b"]
    assert all(ref.quote == "😀重" and ref.start == 0 and ref.end == 2 for ref in refs)


def test_composite_mapping_rejects_synthetic_only_intervals_and_tampering() -> None:
    snapshot = _snapshot(_payload(units=(_proven_table("a"), _proven_table("b"))))
    packet = evidence_document_from_snapshot(snapshot, role="claims").packets[0]
    references = resolve_packet_span(snapshot, packet, 0, len(packet.text))
    assert [ref.unit_id for ref in references] == ["a", "b"]
    assert all(ref.start == 0 and ref.end == 17 for ref in references)
    with pytest.raises(SnapshotIntegrityError, match="synthetic"):
        resolve_packet_span(snapshot, packet, 17, 18)
    with pytest.raises(SnapshotIntegrityError):
        resolve_packet_span(snapshot, packet.model_copy(update={"text": "wrong"}), 0, 2)


def test_cycles_are_ambiguous_and_long_context_chains_are_complete() -> None:
    units = tuple(
        SnapshotUnitSource(
            source_unit_id=f"u{i}",
            chunk_id="chain",
            kind="heading" if i else "prose",
            text=f"source {i}",
            locator=f"unit:{i}",
            dependencies=(SnapshotDependencySource(kind="context", target_unit_id=f"u{i + 1}"),)
            if i < 1099
            else (),
        )
        for i in range(1100)
    )
    snapshot = _snapshot(_payload(units=units))
    assert snapshot.units[0].metadata["context_status"] == "complete"
    assert len(select_snapshot(snapshot, "claims").units) == 1100
    cyclic = (
        replace(
            units[0], dependencies=(SnapshotDependencySource(kind="context", target_unit_id="u1"),)
        ),
        replace(
            units[1], dependencies=(SnapshotDependencySource(kind="context", target_unit_id="u0"),)
        ),
    )
    snapshot = _snapshot(_payload(units=cyclic))
    assert all(unit.metadata["context_status"] == "ambiguous" for unit in snapshot.units)


def test_real_cleaner_preserves_raw_text_and_snapshot_preserves_disposition() -> None:
    from plugins.corpus.preparation.clean import clean_reader_result, verify_clean_region
    from plugins.corpus.preparation.contract import DocumentFormat, UnitLocation, UnitStatus
    from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderResult

    for status in (UnitStatus.KEPT, UnitStatus.REVIEW_REQUIRED):
        raw = "😀营收  100亿元\n仅在并购完成时成立。"
        candidate = CandidateUnit(
            ordinal=0,
            kind="paragraph",
            status=status,
            reasons=(),
            raw_text=raw,
            location=UnitLocation(page=1),
        )
        clean = clean_reader_result(
            ReaderResult(
                format=DocumentFormat.MARKDOWN,
                extractor_rev="synthetic",
                source_path="synthetic.md",
                page_count=1,
                units=(candidate,),
                issues=(),
            )
        )
        region = clean.regions[0]
        verify_clean_region(raw, region.clean_view, region.mapping)
        source = SnapshotUnitSource(
            source_unit_id="cleaned",
            chunk_id="raw",
            kind=candidate.kind,
            text=candidate.raw_text,
            locator="page:1",
            content_hash=candidate.content_hash,
            status=region.status.value,
            reasons=region.reasons,
        )
        snapshot = _snapshot(_payload(units=(source,)))
        packet = evidence_document_from_snapshot(snapshot, role="claims").packets[0]
        assert packet.text == raw
        assert (packet.status == "available") == (status is UnitStatus.KEPT)
        if region.clean_view is not None and region.clean_view != raw:
            with pytest.raises(SnapshotIntegrityError, match="content hash"):
                _snapshot(_payload(units=(replace(source, text=region.clean_view),)))


@pytest.mark.parametrize("kind", ["condition", "negation", "attribution"])
def test_source_qualifications_survive_deterministic_fact_projection(kind: str) -> None:
    row = _proven_table()
    note = SnapshotUnitSource(
        source_unit_id="note",
        chunk_id="notes",
        kind="table_note",
        text="仅在条件成立时适用；不是无条件事实。",
        locator="page:2/note",
    )
    row = replace(
        row,
        dependencies=(
            SnapshotDependencySource(
                kind=kind,
                target_unit_id="note",
                target_chunk_id="notes",
                required_for=("cite", "compare", "calculate"),
            ),
        ),
    )
    payload = _payload(units=(row, note))
    snapshot = _snapshot(replace(payload, document=replace(payload.document, subject="999999.SZ")))
    run = build_evidence_run_from_snapshot(snapshot)
    assert run.facts
    for fact in run.facts:
        assert "calculate" not in fact.usable_for
        assert "compare" not in fact.usable_for
        assert f"source_{kind}_dependency" in fact.reasons
        assert fact.evidence_alignment["dependency_spans"][0]["unit_id"] == "note"


def test_context_status_is_monotone_under_a_cycle_with_missing_leaf() -> None:
    first = SnapshotUnitSource(
        source_unit_id="a",
        chunk_id="graph",
        kind="paragraph",
        text="预测成立。",
        locator="a",
        dependencies=(SnapshotDependencySource(kind="context", target_unit_id="b"),),
    )
    second = replace(
        first,
        source_unit_id="b",
        locator="b",
        dependencies=(
            SnapshotDependencySource(kind="context", target_unit_id="a"),
            SnapshotDependencySource(kind="condition", target_unit_id="missing"),
        ),
    )
    snapshot = _snapshot(_payload(units=(first, second)))
    assert all(unit.metadata["context_status"] == "missing" for unit in snapshot.units)


def test_snapshot_detaches_mutable_adapter_metadata_and_rejects_old_builder() -> None:
    source_metadata = {"nested": {"labels": ["original"]}}
    payload = _payload()
    source = replace(payload.units[0], metadata=source_metadata)
    snapshot = _snapshot(replace(payload, units=(source,)))
    source_metadata["nested"]["labels"].append("mutated")
    snapshot.verify_identity()
    assert snapshot.units[0].metadata["nested"] == {"labels": ["original"]}
    data = snapshot.model_dump(mode="json")
    data["parser_versions"]["snapshot"] = "structured-snapshot-1"
    with pytest.raises(SnapshotIntegrityError, match="rebuild"):
        EvidenceSnapshot.model_validate(data).verify_identity()


@pytest.mark.parametrize("role", ["claims", "material_items"])
def test_gap_tampering_is_rejected_at_role_entrypoints(role: str) -> None:
    snapshot = _snapshot().model_copy(update={"gaps": ()})
    with pytest.raises(SnapshotIntegrityError, match="gap hash"):
        if role == "claims":
            build_evidence_run_from_snapshot(snapshot)
        else:
            extract_material_understanding_from_snapshot(snapshot, llm=None, max_calls=0)


def test_runtime_snapshot_remains_compatible_with_frozen_v1_shape() -> None:
    import runpy

    validator = runpy.run_path(str(Path(__file__).with_name("test_corpus_structured_contracts.py")))
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / ".scratch"
            / "claims-r2-role-isolation"
            / "contracts"
            / "v1"
            / "evidence-snapshot.schema.json"
        ).read_text()
    )
    assert (
        validator["_validation_errors"](_snapshot().model_dump(mode="json"), schema, schema) == []
    )


def test_unavailable_cleaning_regions_do_not_leak_as_neighbor_context() -> None:
    from plugins.corpus.material_semantics import build_item_jsonl_prompt, build_material_prompt

    kept = SnapshotUnitSource(
        source_unit_id="kept",
        chunk_id="kept",
        kind="paragraph",
        text="预计收入增长。",
        locator="kept",
    )
    excluded = replace(
        kept,
        source_unit_id="excluded",
        chunk_id="excluded",
        text="EXCLUDED_CONTENT_SENTINEL",
        status="out_of_scope",
    )
    snapshot = _snapshot(_payload(units=(excluded, kept)))
    document = evidence_document_from_snapshot(snapshot, role="material_items")
    previous, packet = document.packets
    assert previous.status == "partial"
    for prompt in (
        build_material_prompt(document, packet, previous=previous, following=None),
        build_item_jsonl_prompt(document, packet, previous=previous, following=None, max_items=5),
    ):
        assert excluded.text not in prompt
