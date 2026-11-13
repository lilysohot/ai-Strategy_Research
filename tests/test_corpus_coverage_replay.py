"""覆盖映射验收：分母/分子、唯一区间并集、页数与覆盖率正交、两套 locator 后台映射。"""

from __future__ import annotations

import pytest

from plugins.corpus.coverage import (
    SOURCE_EXTRACTION_UNKNOWN,
    Delivery,
    UnitRange,
    coverage_report,
    map_native_to_document,
    merge_intervals,
)
from plugins.corpus.ledger import DELIVERED, ConsumptionLedger

DOC = "cv2:" + "b" * 64
U1 = "chunk:document1/unit%3A0001"
U2 = "chunk:document1/unit%3A0002"
U3 = "chunk:document1/unit%3A0003"


def test_merge_intervals_joins_adjacent_page_fragments() -> None:
    assert merge_intervals([(0, 60), (60, 100), (20, 40), (140, 150)]) == [
        (0, 100),
        (140, 150),
    ]


def test_coverage_uses_delivered_union_not_page_count() -> None:
    units = [UnitRange(U1, "unit:0001", 100), UnitRange(U2, "unit:0002", 100)]
    deliveries = [
        Delivery(DOC, U1, 0, 60),  # 长单元第一页
        Delivery(DOC, U1, 60, 100),  # 续页，必须与上一片合并
        Delivery(DOC, U1, 0, 60),  # 同轮重复投递，不能重复计数
        Delivery(DOC, U2, 0, 100),
    ]
    report = coverage_report(doc_id=DOC, units=units, deliveries=deliveries, page_count=17)
    assert report["denominator"] == {"unit_count": 2, "total_chars": 200}
    assert report["numerator"]["delivered_chars"] == 200
    assert report["ratio"] == 1.0 and report["complete"] is True
    # 页数只作效率指标：改页数不影响任何覆盖字段。
    assert report["efficiency"] == {"page_count": 17}
    assert (
        coverage_report(doc_id=DOC, units=units, deliveries=deliveries, page_count=3)[
            "numerator"
        ]
        == report["numerator"]
    )


def test_partial_coverage_reports_gaps_and_keeps_extraction_unknown() -> None:
    units = [UnitRange(U3, "unit:0003", 100)]
    report = coverage_report(
        doc_id=DOC,
        units=units,
        deliveries=[Delivery(DOC, U3, 30, 70)],
        page_count=2,
    )
    assert report["ratio"] == 0.4 and report["complete"] is False
    assert report["missing"][0]["missing"] == [(0, 30), (70, 100)]
    # 已提取的 OCR 计入入库文本覆盖，但不能反推原 PDF 提取完整。
    assert report["source_extraction_completeness"] == SOURCE_EXTRACTION_UNKNOWN
    assert report["scope"] == "ingested_text"


def test_ledger_coverage_deliveries_deduplicate_by_identity() -> None:
    ledger = ConsumptionLedger()
    ledger.delivered[(DOC, U1, 0, 50)] = DELIVERED
    ledger.delivered[(DOC, U1, 50, 100)] = DELIVERED
    ledger.delivered[(DOC, U2, 0, 100)] = DELIVERED  # 其它单元的另一份投递
    report = ledger.coverage_map(
        [UnitRange(U1, "unit:0001", 100), UnitRange(U2, "unit:0002", 100)],
        doc_id=DOC,
        page_count=9,
    )
    assert report["numerator"]["delivered_chars"] == 200
    assert report["complete"] is True
    assert report["efficiency"]["page_count"] == 9


def test_native_document_mapping_never_guesses() -> None:
    known = {
        "unit:0001": UnitRange(U1, "unit:0001", 100),
        "unit:0002": UnitRange(U2, "unit:0002", 100),
    }
    out = map_native_to_document(
        ["chunk:native1/a:body:0001/hash", "chunk:native1/b:body:0002/hash", "chunk:native1/c"],
        native_to_units={
            "chunk:native1/a:body:0001/hash": ("unit:0001", "unit:0002"),
            "chunk:native1/b:body:0002/hash": ("unit:9999",),  # 查得到 id 但无此单元
        },
        known_units=known,
    )
    assert out["mapped"] == {"chunk:native1/a:body:0001/hash": [U1, U2]}
    assert out["unmapped"] == ["chunk:native1/b:body:0002/hash", "chunk:native1/c"]
    assert out["mapped_count"] == 1 and out["unmapped_count"] == 2


@pytest.mark.parametrize("page_count", [1, 17, 100])
def test_page_count_never_enters_denominator(page_count: int) -> None:
    report = coverage_report(
        doc_id=DOC,
        units=[UnitRange(U1, "unit:0001", 100)],
        deliveries=[Delivery(DOC, U1, 0, 100)],
        page_count=page_count,
    )
    assert report["denominator"]["total_chars"] == 100
    assert report["ratio"] == 1.0
