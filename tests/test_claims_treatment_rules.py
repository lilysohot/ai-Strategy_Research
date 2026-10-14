"""Pre-registered produce-side treatment rules T1/T2/T3 (95/99 号 §七, landed in 101 号).

These tests pin the properties that make the treatment arm *the arm it says it is*:

* **T1** the extraction contract no longer invites rating opinions, the produce-side predicate is the
  exact mirror of the signed C1 caliber, and a bind-produced categorical status is not mistaken for a
  valueless record;
* **T2** a missing ``period``/``unit`` is filled only from a carrier inside the same packet, with
  provenance, and a record without a carrier stays empty (no guessing);
* **T3** repeated renderings of the same subject+metric+quote-span *and kind* merge deterministically,
  in the pre-registered priority order, while same-coordinate rows of a different kind stay separate
  because that is a conflict (``conflicting_fact_kinds``), not a repeat.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from plugins.corpus.claims_binding import recover_packet_coordinates
from plugins.corpus.claims_detail import (
    V2_OUTPUT_CONTRACT,
    ClaimRecord,
    is_claims_scope_candidate,
)
from plugins.corpus.evidence_pipeline import EvidenceFact, _merge_repeated_facts, _render_key
from tools.check_claims_gate import _claim_of, _is_role_external

SCRATCH = Path(__file__).resolve().parents[1] / ".scratch/claims-r2-role-isolation"
POOL = (
    SCRATCH
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)


def _record(**overrides: object) -> ClaimRecord:
    base: dict[str, object] = {
        "doc_id": "d",
        "source_rev": "rev",
        "seq": 1,
        "locator": "p1",
        "claim_text": "营收 1741 亿元",
        "evidence_quote": "营收 1741 亿元",
        "scope": "company",
        "subject": "600519.SH",
        "metric": "营业收入",
        "kind": "fact",
        "value_text": "1741 亿元",
        "value_num": Decimal("174100000000"),
        "unit_raw": "亿元",
        "unit": "元",
        "period_raw": "2026H1",
        "period_end": "2026-06-30",
        "period_grain": "half",
        "known_at": "2026-09-06",
    }
    return ClaimRecord(**{**base, **overrides})  # type: ignore[arg-type]


def _fact(record: ClaimRecord, *, packet_id: str, index: int = 0) -> EvidenceFact:
    return EvidenceFact(fact_id=f"f{index}", packet_id=packet_id, claim=record)


# ---------------------------------------------------------------- T1


def test_contract_no_longer_invites_opinion_claims() -> None:
    assert "评级" in V2_OUTPUT_CONTRACT
    assert "不要输出" in V2_OUTPUT_CONTRACT
    assert "明确评级观点" not in V2_OUTPUT_CONTRACT, "旧的许可必须被拿掉，否则提示词仍在要 opinion"
    assert "kind 只能是 fact/forecast" in V2_OUTPUT_CONTRACT


def test_produce_side_predicate_is_the_caliber_mirror() -> None:
    assert is_claims_scope_candidate(_record())
    assert not is_claims_scope_candidate(_record(kind="opinion", value_num=None))
    assert not is_claims_scope_candidate(_record(value_text=None, value_num=None))
    # 分类状态值由 bind 补出 value_text="status"，属于合法记录，不得提前过滤
    assert is_claims_scope_candidate(
        _record(value_text="mass_production", unit_raw="status", unit="status")
    )


def test_produce_side_predicate_matches_the_frozen_pool_caliber() -> None:
    rows = json.loads(POOL.read_text(encoding="utf-8"))["adjudications"]
    for row in rows:
        claim = _claim_of(row)
        in_scope = is_claims_scope_candidate(
            ClaimRecord(
                doc_id="d",
                source_rev="r",
                seq=0,
                locator="p",
                claim_text="x",
                evidence_quote=None,
                kind=str(claim.get("kind") or "fact"),
                value_text=claim.get("value_text"),
            )
        )
        assert in_scope is not _is_role_external(claim)


# ---------------------------------------------------------------- T2


def test_missing_period_is_filled_from_a_same_packet_carrier() -> None:
    carrier = _record()
    gap = _record(
        period_raw=None,
        period_end=None,
        period_grain=None,
        evidence_quote="营收 1741 亿元（同一指标的另一处表述）",
    )
    recovered, notes = recover_packet_coordinates([carrier, gap])
    filled = recovered[1]
    assert filled.period_raw == carrier.period_raw
    assert filled.period_end == carrier.period_end
    assert filled.qualifiers["period_basis"] == "packet_sibling_same_metric"
    assert notes["period_from_same_metric"] == 1
    assert recovered[0] is carrier, "已有坐标的记录不得被改写"


def test_same_quote_carrier_wins_over_same_metric() -> None:
    carrier = _record(metric="营业总收入")
    gap = _record(metric="营业收入", period_raw=None, period_end=None, period_grain=None)
    recovered, notes = recover_packet_coordinates([carrier, gap])
    assert recovered[1].qualifiers["period_basis"] == "packet_sibling_same_quote"
    assert notes["period_from_same_quote"] == 1


def test_missing_unit_is_filled_from_a_same_metric_carrier() -> None:
    carrier = _record()
    gap = _record(unit_raw=None, unit=None, period_raw="2026H1", period_end="2026-06-30")
    recovered, notes = recover_packet_coordinates([carrier, gap])
    assert recovered[1].unit_raw == carrier.unit_raw
    assert recovered[1].unit == carrier.unit
    assert notes["unit_from_same_metric"] == 1


def test_record_without_any_carrier_stays_empty() -> None:
    alone = _record(period_raw=None, period_end=None, unit_raw=None, unit=None)
    recovered, notes = recover_packet_coordinates([alone])
    assert recovered[0] is alone
    assert sum(notes.values()) == 0, "没有载体时不得凭空补齐（不猜）"


# ---------------------------------------------------------------- T3


def test_repeated_renderings_merge_with_the_coordinate_first_priority() -> None:
    complete = _fact(_record(), packet_id="a", index=0)
    incomplete = _fact(
        _record(period_raw=None, period_end=None, period_grain=None), packet_id="b", index=1
    )
    kept, dedupe = _merge_repeated_facts([incomplete, complete])
    assert len(kept) == 1 and kept[0] is complete, "坐标更完整者留下"
    assert dedupe["groups"] == 1 and dedupe["merged_facts"] == 1
    assert dedupe["by_kept_packet"] == {"a": 1}


def test_same_coordinates_but_different_kind_are_not_merged() -> None:
    forecast = _fact(_record(kind="forecast"), packet_id="a", index=0)
    fact = _fact(_record(kind="fact"), packet_id="a", index=1)
    kept, dedupe = _merge_repeated_facts([forecast, fact])
    assert len(kept) == 2, "同坐标不同 kind 是 conflicting_fact_kinds 冲突，不是重复渲染"
    assert dedupe["groups"] == 0


def test_different_quote_span_is_not_merged() -> None:
    first = _fact(_record(), packet_id="a", index=0)
    second = _fact(_record(evidence_quote="别的原文 1741 亿元"), packet_id="a", index=1)
    kept, dedupe = _merge_repeated_facts([first, second])
    assert len(kept) == 2 and dedupe["groups"] == 0


def test_frozen_pool_merges_two_groups_and_keeps_the_complete_one() -> None:
    rows = json.loads(POOL.read_text(encoding="utf-8"))["adjudications"]
    facts: list[EvidenceFact] = []
    coordinates: dict[tuple[str, tuple[str, ...]], str | None] = {}
    for index, row in enumerate(rows):
        claim = _claim_of(row)
        payload = {
            key: value
            for key, value in claim.items()
            if key in ClaimRecord.__dataclass_fields__ and key not in {"value_num", "reason_codes"}
        }
        value = claim.get("value_num")
        record = ClaimRecord(
            **payload,  # type: ignore[arg-type]
            value_num=None if value is None else Decimal(str(value)),
            reason_codes=tuple(claim.get("reason_codes") or ()),
        )
        if not is_claims_scope_candidate(record):
            continue
        packet_id = str(row["original_candidate"].get("packet_id"))
        facts.append(_fact(record, packet_id=packet_id, index=index))
        coordinates[(packet_id, _render_key(record))] = record.period_raw

    kept, dedupe = _merge_repeated_facts(facts)
    assert dedupe["groups"] == 2, "95 号在冻结池上量到的两组重复渲染必须都在合并范围内"
    assert dedupe["merged_facts"] == 2
    assert len({_render_key(fact.claim) for fact in kept}) == len(kept), "合并后不得残留同键多行"

    detail = {tuple(item["key"]): item for item in dedupe["detail"]}
    profitable_key = next(key for key in detail if "归母净利润" in key[1])
    kept_coordinate = coordinates[(detail[profitable_key]["kept_packet_id"], profitable_key)]
    assert kept_coordinate, (
        "载重并列（归母净利润）必须保留坐标更完整的那条：规则只看坐标/引用一致/文件序，"
        "不看金标——这里正是靠 period_raw 完整度保住了 matched 行"
    )
