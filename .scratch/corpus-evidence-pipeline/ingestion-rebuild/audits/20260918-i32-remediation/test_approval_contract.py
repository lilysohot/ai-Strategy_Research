"""Public approval/projection contract regressions; no real approvals or model/PG I/O."""

import copy
import runpy
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[2]
APP = runpy.run_path(str(BASE / "i3s2_apply_decisions.py"))
VERIFY = runpy.run_path(str(BASE / "i3s2_verify_candidates.py"))


@pytest.fixture
def case():
    payload, gold, slots = VERIFY["_synthetic_payload"]()
    return payload, gold, slots, VERIFY["_synthetic_decisions"](payload)


def check(case):
    return APP["evaluate"](*case)


def test_valid_approval_and_projection(case):
    assert check(case)["ready"]
    projection = APP["project"](*case)
    assert all(
        t["quote"] and t["source_id"] for t in projection["questions"][0]["approved_required"]
    )


def test_source_specific_obligation_requires_that_source(case):
    p, g, s, d = case
    q = p["questions"][0]
    q["satisfy_rule"] = g[0]["satisfy_rule"] = "all"
    q["relevant_sources"].append("source-B")
    g[0]["relevant_sources"] = list(q["relevant_sources"])
    q["candidate_slots"].append("slot-B")
    s.append({**copy.deepcopy(s[0]), "gold_id": "slot-B", "source_id": "source-B"})
    q["pending_human"][0].update(kind="source_coverage", facet_id=None, source_id="source-B")
    q["pending_human"][0]["suggestions"] = [{"slot": "slot-B", "item_index": 1, "role": "primary"}]
    d["facet_decisions"][0]["facet_id"] = None
    assert not check(case)["ready"]
    d["facet_decisions"][0]["chosen"][0]["slot"] = "slot-B"
    assert check(case)["ready"]
    assert {t["source_id"] for t in APP["project"](*case)["questions"][0]["approved_required"]} == {
        "probe-source",
        "source-B",
    }


def test_answer_constraint_cannot_inject_target(case):
    p, g, s, d = case
    p["questions"][0]["pending_human"][0]["kind"] = "answer_constraint"
    p["questions"][0]["answer_constraints"] = ["必须标明预测，不得冒充实际值"]
    d["facet_decisions"][0]["chosen"] = [{"slot": "missing", "item_index": 999}]
    assert not check(case)["ready"]
    with pytest.raises(ValueError):
        APP["project"](*case)
    d["facet_decisions"][0].pop("chosen")
    assert check(case)["ready"]
    assert len(APP["project"](*case)["questions"][0]["approved_required"]) == 1
    assert APP["project"](*case)["questions"][0]["answer_constraints"] == [
        "必须标明预测，不得冒充实际值"
    ]


def test_blanket_residual_cannot_waive_missing_facts(case):
    p, g, s, d = case
    p["questions"][0]["requirement_facets"][1]["text"] = "财政四条收敛路径"
    d["facet_decisions"][0].update(
        residual_accepted=True, residual_reason="missing facts NOT supplied"
    )
    assert not check(case)["ready"]


def test_search_hint_cannot_be_directly_approved(case):
    p, g, s, d = case
    p["questions"][0]["pending_human"][0]["suggestions"] = [
        {"slot": "probe-slot", "item_index": 1, "role": "search_hint"}
    ]
    assert not check(case)["ready"]


def test_metadata_cannot_replace_quote(case):
    p, g, s, d = case
    s[0]["expected_items"][1].update(quote="82.9%", text="门槛口径为年度累计", period="门槛口径")
    assert not check(case)["ready"]


@pytest.mark.parametrize(
    "array,key", [("question_reviews", "query_id"), ("negative_reviews", "query_id")]
)
def test_duplicate_or_unknown_reviews_rejected(case, array, key):
    d = case[3]
    entry = copy.deepcopy(d[array][0])
    entry["decision"] = "需补要件"
    d[array].insert(0, entry)
    assert not check(case)["ready"]
    d[array][0][key] = "unknown"
    assert not check(case)["ready"]


@pytest.mark.parametrize("field", ["query_id", "facet_id"])
def test_facet_identity_must_match(case, field):
    case[3]["facet_decisions"][0][field] = "wrong"
    assert not check(case)["ready"]


def test_negative_review_needs_reason(case):
    case[3]["negative_reviews"][0].pop("reason")
    assert not check(case)["ready"]


def lexical_mapping(case, kind="lexical_mismatch"):
    p, _, s, _ = case
    facet = p["questions"][0]["requirement_facets"][1]
    quote = s[0]["expected_items"][1]["quote"]
    terms = sorted(APP["content_units"](facet["text"]) - APP["content_units"](quote))
    return {
        "kind": kind,
        "facet_id": "q2",
        "requirement": facet["text"],
        "evidence_complete": True,
        "missing_evidence": False,
        "mappings": [
            {
                "terms": terms if kind == "lexical_mismatch" else [],
                "slot": "probe-slot",
                "item_index": 1,
                "quote_span": quote,
                "reason": "SYNTHETIC: 年度合计与年度累计同义，引用确实承载此义务",
            }
        ],
    }


def test_lexical_difference_allows_auditable_mapping_not_waiver(case):
    p, _, _, d = case
    p["questions"][0]["requirement_facets"][1]["text"] = "门槛口径为年度合计"
    assert not check(case)["ready"]
    d["facet_decisions"][0]["lexical_review"] = lexical_mapping(case)
    assert check(case)["ready"]
    projected = APP["project"](*case)
    assert projected["decision_record"]["facet_decisions"][0]["lexical_review"] == lexical_mapping(
        case
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "fake_quote",
        "missing_evidence",
        "wrong_terms",
        "wrong_identity",
        "empty_mapping",
        "unselected_item",
    ],
)
def test_lexical_review_is_not_blanket_override(case, mutation):
    p, _, _, d = case
    p["questions"][0]["requirement_facets"][1]["text"] = "年度合计口径"
    review = lexical_mapping(case)
    if mutation == "fake_quote":
        review["mappings"][0]["quote_span"] = "并不存在的原文"
    elif mutation == "missing_evidence":
        review["missing_evidence"] = True
    elif mutation == "wrong_terms":
        review["mappings"][0]["terms"] = []
    elif mutation == "wrong_identity":
        review["facet_id"] = "wrong"
    elif mutation == "empty_mapping":
        review["mappings"] = []
    else:
        review["mappings"][0]["item_index"] = 0
    d["facet_decisions"][0]["lexical_review"] = review
    assert not check(case)["ready"]


def test_explicit_reselection_can_promote_verified_hint(case):
    p, _, _, d = case
    p["questions"][0]["pending_human"][0]["suggestions"][0]["role"] = "search_hint"
    d["facet_decisions"][0]["decision"] = "改选"
    assert not check(case)["ready"]
    d["facet_decisions"][0]["anchor_review"] = lexical_mapping(case, "anchor_reselection")
    assert check(case)["ready"]


def test_status_clarifications_are_unique_and_known(case):
    p, _, _, d = case
    p["human_status_conflicts"] = [{"gold_id": "probe-slot"}]
    valid = {"gold_id": "probe-slot", "resolution": "残留描述", "reason": "SYNTHETIC"}
    d["human_status_clarifications"] = [valid]
    assert check(case)["ready"]
    d["human_status_clarifications"].append({**valid, "resolution": "实质未决"})
    assert not check(case)["ready"]
    d["human_status_clarifications"][-1]["gold_id"] = "unknown"
    assert not check(case)["ready"]


@pytest.mark.parametrize(
    "chosen",
    [
        None,
        "invalid",
        [None],
        [{"slot": "probe-slot", "item_index": True}],
        [{"slot": "probe-slot", "item_index": -1}],
        [{"slot": "probe-slot", "item_index": 1}, {}],
    ],
)
def test_malformed_chosen_fails_closed(case, chosen):
    case[3]["facet_decisions"][0]["chosen"] = chosen
    assert not check(case)["ready"]


@pytest.mark.parametrize(
    "field,value", [("quote", ""), ("quote", "invented"), ("source_id", "wrong"), ("locator", [])]
)
def test_machine_target_also_requires_canonical_reference(case, field, value):
    case[0]["questions"][0]["targets"][0][field] = value
    assert not check(case)["ready"]
    with pytest.raises(ValueError):
        APP["project"](*case)


def test_original_probes_and_real_gate_stay_closed():
    import json

    payload = json.loads((BASE / "i3-2/evidence-targets-candidates.json").read_text())
    gold = APP["load_jsonl"](BASE / "query-gold-frozen.jsonl")
    slots = APP["load_jsonl"](BASE / "source-gold-frozen.jsonl")
    probes, failed = VERIFY["run_probes"](gold, {q["query_id"]: q for q in payload["questions"]})
    assert len(probes) == 16 and failed == 0
    assert APP["evaluate"](payload, gold, slots, None)["stage"] == "no_decisions"


def test_statistical_window_hint_not_marked_full():
    mapper = runpy.run_path(str(BASE / "i3s2_evidence_targets.py"))
    slot = {"gold_id": "table", "source_id": "doc", "locator": {"page": "1"}}
    item = {"quote": "82.9%", "kind": "table_cell", "period": "年度平均开工率"}
    suggestion = mapper["_suggestion"](slot, 0, item, "年度平均开工率", "search", False, {}, 1)
    assert suggestion["adequacy"] == "partial"
    assert suggestion["uncovered_terms"]
