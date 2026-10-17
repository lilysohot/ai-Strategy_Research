"""S0 文档结构 shadow 契约测试。"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from plugins.corpus.preparation.contract import DocumentFormat, UnitLocation, UnitStatus
from plugins.corpus.preparation.engine import (
    _serialize_parse_checkpoint,
    _validate_parse_checkpoint,
)
from plugins.corpus.preparation.readers import (
    CandidateUnit,
    ReaderError,
    ReaderResult,
    project_candidate_units,
)
from plugins.corpus.preparation.structure import (
    RelationCertainty,
    RelationKind,
    StructuredDocument,
    StructureNode,
    StructureRelation,
    TextOrigin,
)


def _units() -> tuple[CandidateUnit, ...]:
    return (
        CandidateUnit(
            ordinal=0,
            kind="heading",
            status=UnitStatus.KEPT,
            reasons=(),
            raw_text="经营摘要",
            location=UnitLocation(page=1, bbox=(10.0, 20.0, 100.0, 40.0)),
        ),
        CandidateUnit(
            ordinal=1,
            kind="table_row",
            status=UnitStatus.KEPT,
            reasons=("tbl[0]",),
            raw_text="收入 | 100",
            location=UnitLocation(
                page=1,
                bbox=(10.0, 50.0, 180.0, 70.0),
                cells=((1, 0), (1, 1)),
                label_path=("指标", "收入 指标"),
            ),
        ),
    )


def _result() -> ReaderResult:
    return ReaderResult(
        format=DocumentFormat.PDF,
        extractor_rev="reader-test-1",
        source_path="/inputs/report.pdf",
        page_count=1,
        units=_units(),
        issues=(),
    )


def test_reader_result_builds_lossless_shadow_structure() -> None:
    result = _result()

    assert result.structure is not None
    assert [node.node_id for node in result.structure.nodes] == ["unit:000000", "unit:000001"]
    assert all(node.text_origin is TextOrigin.NATIVE for node in result.structure.nodes)
    assert len(result.structure.relations) == 1
    relation = result.structure.relations[0]
    assert relation.kind is RelationKind.NEXT_IN_READING_ORDER
    assert (relation.source_id, relation.target_id) == ("unit:000000", "unit:000001")
    assert project_candidate_units(result.structure) == result.units


def test_reader_result_rejects_structure_that_changes_compatibility_view() -> None:
    result = _result()
    assert result.structure is not None
    changed = replace(result.structure.nodes[0], raw_text="被修改")
    structure = StructuredDocument(
        nodes=(changed, *result.structure.nodes[1:]),
        relations=result.structure.relations,
    )

    with pytest.raises(ReaderError, match="兼容投影"):
        replace(result, structure=structure)


def test_parse_checkpoint_round_trips_structure() -> None:
    result = _result()
    checkpoint = _serialize_parse_checkpoint(
        "source-1",
        result,
        result.extractor_rev,
        tuple(unit.content_hash for unit in result.units),
    )

    payload = json.loads(checkpoint)
    assert payload["checkpoint_schema_rev"] == "parse-checkpoint-4"
    assert payload["structure"]["nodes"][1]["node_id"] == "unit:000001"
    assert payload["structure"]["nodes"][1]["ordinal"] == 1
    assert payload["structure"]["nodes"][1]["text_origin"] == "native_text"

    restored, reason = _validate_parse_checkpoint(
        checkpoint,
        "source-1",
        result.extractor_rev,
    )

    assert reason is None
    assert restored == result


def test_nonprojected_structure_nodes_round_trip_without_changing_units() -> None:
    base = _result()
    assert base.structure is not None
    table = StructureNode(
        node_id="pdf:p0001:t000",
        ordinal=None,
        kind="table",
        status=UnitStatus.KEPT,
        reasons=("tbl[0]",),
        raw_text="",
        location=UnitLocation(page=1, bbox=(10.0, 45.0, 180.0, 75.0)),
    )
    cell = StructureNode(
        node_id="pdf:p0001:t000:r0001:c0001",
        ordinal=None,
        kind="table_cell",
        status=UnitStatus.KEPT,
        reasons=("tbl[0]",),
        raw_text="100",
        location=UnitLocation(
            page=1,
            bbox=(10.0, 45.0, 180.0, 75.0),
            cells=((1, 1),),
            label_path=("收入 指标",),
        ),
    )
    relations = (
        *base.structure.relations,
        StructureRelation(
            source_id=table.node_id,
            target_id=cell.node_id,
            kind=RelationKind.CONTAINS,
            certainty=RelationCertainty.CONFIRMED,
            evidence="table_grid_membership",
        ),
    )
    rich = replace(
        base,
        structure=StructuredDocument(
            nodes=(*base.structure.nodes, table, cell),
            relations=relations,
        ),
    )
    assert project_candidate_units(rich.structure) == rich.units

    checkpoint = _serialize_parse_checkpoint(
        "source-1",
        rich,
        rich.extractor_rev,
        tuple(unit.content_hash for unit in rich.units),
    )
    restored, reason = _validate_parse_checkpoint(checkpoint, "source-1", rich.extractor_rev)

    assert reason is None
    assert restored == rich
