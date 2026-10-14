"""One-shot governance application (94 号): branch dispatch, refusal discipline, draft-only writes.

The tool turns a *signed* 93-号 decision record into drafts. These tests pin the properties that
make it safe to run unattended:

* an unsigned or incomplete record is refused, and ``--simulate`` never writes anything;
* every M1/M2/M3 branch resolves to a declared outcome, and the recomputed gate variants reproduce
  the signed gate v3 blockers string-for-string (the recomputation is not a new caliber);
* branches that need a further signed change (P03 binding record, new gate axis, vocabulary
  extension) say so instead of landing;
* the v4.5 draft is a draft: frozen values survive, the mis-named release-line leaf is renamed with
  its value preserved, and no frozen artifact is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.apply_claims_governance_decisions import (
    DEFAULT_CONTRACT_V44,
    DEFAULT_GATE_V3,
    DEFAULT_PLAN,
    DecisionError,
    build_application,
    load_json,
    main,
    parse_simulation,
    read_decisions,
    sha256,
)

SCRATCH = Path(__file__).resolve().parents[1] / ".scratch/claims-r2-role-isolation"


def _contract() -> dict:
    return load_json(DEFAULT_CONTRACT_V44)


def _gate() -> dict:
    return load_json(DEFAULT_GATE_V3)


def _application(decisions: dict[str, str]) -> dict:
    return build_application(decisions, contract=_contract(), gate=_gate(), simulated=True)


def _signed_plan(overrides: dict[str, str] | None = None) -> dict:
    plan = load_json(DEFAULT_PLAN)
    plan["decision_signoff"] = {
        "reviewer": "xyl",
        "adjudicator": "xyl",
        "signed_on": "2026-10-14",
    }
    for cell in plan["cells"]:
        cell["status"] = "decided"
        cell["value"] = (overrides or {}).get(cell["id"]) or {
            "M1": "b_scaled_floor",
            "M2": "report_only",
            "M3": "O1_status_quo",
        }[cell["id"]]
    return plan


# ------------------------------------------------------------------ refusal discipline


def test_unsigned_plan_is_refused() -> None:
    with pytest.raises(DecisionError, match="decision_signoff"):
        read_decisions(load_json(DEFAULT_PLAN))


def test_blank_cell_value_is_refused() -> None:
    plan = _signed_plan()
    next(cell for cell in plan["cells"] if cell["id"] == "M2")["value"] = None
    with pytest.raises(DecisionError, match="M2 未裁定"):
        read_decisions(plan)


def test_signed_plan_reads_every_cell() -> None:
    decisions = read_decisions(_signed_plan())
    assert decisions == {"M1": "b_scaled_floor", "M2": "report_only", "M3": "O1_status_quo"}


def test_unknown_cell_or_value_is_refused() -> None:
    with pytest.raises(DecisionError, match="未知格"):
        _application({"M9": "x"})
    with pytest.raises(DecisionError, match="M1 取值未知"):
        _application({"M1": "d_something_else"})
    with pytest.raises(DecisionError, match="--simulate 需要"):
        parse_simulation("M1")


def test_simulate_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "never"
    assert (
        main(["--simulate", "M1=b_scaled_floor,M2=report_only,M3=O1_status_quo", "--out", str(out)])
        == 0
    )
    assert not out.exists()
    assert "[simulate] 未写盘、未计入决定。" in capsys.readouterr().out


def test_apply_refuses_an_unsigned_plan(tmp_path: Path) -> None:
    with pytest.raises(DecisionError, match="decision_signoff"):
        main(["--apply", "--out", str(tmp_path / "out")])
    assert not (tmp_path / "out").exists()


# ------------------------------------------------------------------ M1


@pytest.mark.parametrize(
    ("value", "floors", "blockers"),
    [
        (
            "a_transplant",
            {"accepted_records_total_min": 40, "accepted_records_per_source_min": 20},
            4,
        ),
        (
            "b_scaled_floor",
            {"accepted_records_total_min": 17, "accepted_records_per_source_min": 8},
            1,
        ),
        (
            "b_scaled_ceil",
            {"accepted_records_total_min": 17, "accepted_records_per_source_min": 9},
            1,
        ),
        ("c_diagnostic", None, 1),
    ],
)
def test_m1_branches_reproduce_the_signed_gate_variants(
    value: str, floors: dict | None, blockers: int
) -> None:
    block = _application({"M1": value})["blocks"]["M1"]
    assert block["recomputed"]["floors"] == floors
    assert len(block["recomputed"]["rate_blockers"]) == blockers
    assert block["recomputed"]["rate_gate_passed"] is False  # precision stays the blocker


def test_recomputation_matches_the_signed_gate_string_for_string() -> None:
    regression = _application({"M1": "a_transplant"})["regression"]
    assert (
        regression["recomputed_variant_a_blockers"]
        == regression["gate_v3_recorded_variant_a_blockers"]
    )


def test_m1_landable_branches_declare_ready_landing() -> None:
    for value in ("a_transplant", "b_scaled_floor", "b_scaled_ceil"):
        block = _application({"M1": value})["blocks"]["M1"]
        assert block["code_landing"] == "ready"
        assert block["contract_leaves"] == {
            "role_sections.claims.accepted_records_total_min": block["recomputed"]["floors"][
                "accepted_records_total_min"
            ],
            "role_sections.claims.accepted_records_per_source_min": block["recomputed"]["floors"][
                "accepted_records_per_source_min"
            ],
        }
    diagnostic = _application({"M1": "c_diagnostic"})["blocks"]["M1"]
    assert diagnostic["code_landing"] == "requires_separate_change"
    assert diagnostic["contract_leaves"] == {}
    assert diagnostic["work_order"]


# ------------------------------------------------------------------ M2 / M3


def test_m2_report_only_lands_but_exists_needs_a_p03_record() -> None:
    report = _application({"M2": "report_only"})["blocks"]["M2"]
    assert report["code_landing"] == "ready"
    assert report["contract_leaves"][
        "claims_thresholds.release_line.per_source_precision_axis"
    ] == ("report_only")
    exists = _application({"M2": "exists"})["blocks"]["M2"]
    assert exists["code_landing"] == "requires_separate_change"
    assert exists["blocked_on"] == "P03 绑定记录（新字段）"
    assert any("EXPECTED_FIELD_SET" in item["site"] for item in exists["work_order"])


def test_m3_o2_is_a_proposal_and_o1_is_a_status_quo_landing() -> None:
    status_quo = _application({"M3": "O1_status_quo"})["blocks"]["M3"]
    assert status_quo["code_landing"] == "ready"
    assert status_quo["contract_leaves"]["claims_use_grading.implementation"] == (
        "status_quo_axis_withdrawal"
    )
    remap = _application({"M3": "O2_remap_two_codes"})["blocks"]["M3"]
    assert remap["code_landing"] == "requires_separate_change"
    assert remap["contract_leaves"] == {}
    assert remap["proposed_patch"]["measured_delta"]["delta"] == 15
    extend = _application({"M3": "O3_extend_vocabulary"})["blocks"]["M3"]
    assert any("store.py:332" in item["site"] for item in extend["work_order"])


# ------------------------------------------------------------------ drafts


def test_v45_draft_is_a_draft_with_the_decided_leaves() -> None:
    draft = _application({"M1": "b_scaled_floor", "M2": "report_only"})["contract_v45_draft"]
    assert draft["status"] == "draft_pending_human_signature"
    assert draft["signoff"] == {"signed_by": None, "signed_on": None}
    assert draft["supersedes"]["sha256"] == sha256(DEFAULT_CONTRACT_V44)
    claims = draft["role_sections"]["claims"]
    assert claims["accepted_records_total_min"] == 17
    assert claims["accepted_records_per_source_min"] == 8
    # The signed sentinels and target total survive untouched.
    assert claims["review_assertions"] == ["NT-C11", "NT-C12", "NT-C13"]
    assert claims["target_total"] == 20


def test_v45_draft_renames_the_misnamed_release_leaf_without_losing_its_value() -> None:
    draft = _application({"M2": "report_only"})["contract_v45_draft"]
    release = draft["claims_thresholds"]["release_line_proposed"]
    assert release["per_source_precision_min"] == 0.55
    assert "target_recall_per_source_min" not in release
    fixes = draft["_application"]["defect_fixes"]
    assert fixes and fixes[0]["value_preserved"] == 0.55


def test_gate_v4_draft_drops_the_precondition_once_m1_is_decided() -> None:
    decided = _application({"M1": "b_scaled_floor"})["gate_v4_draft"]
    assert decided["release_line"]["precondition"] is None
    assert "R3" in decided["release_line_note"]
    assert decided["target_line"]["accepted_records_total_min"] == 17
    assert decided["unfrozen_axes"] == []
    pending = _application({"M2": "report_only"})["gate_v4_draft"]
    assert "pending_caliber" in pending["release_line_note"]
    assert pending["measured_run"]["selected_variant"] is None


def test_apply_writes_drafts_once_and_refuses_a_second_run(tmp_path: Path) -> None:
    plan = tmp_path / "plan-signed.json"
    plan.write_text(json.dumps(_signed_plan(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["--plan", str(plan), "--apply", "--out", str(out)]) == 0
    written = sorted(path.name for path in out.iterdir())
    assert written == [
        "MANIFEST.json",
        "claims-gate-v4.proposed.json",
        "governance-decision-application.json",
        "scoring-contract-v4.5.proposed.json",
    ]
    manifest = load_json(out / "MANIFEST.json")
    assert manifest["decision_signoff"]["reviewer"] == "xyl"
    assert manifest["inputs"]["signed_contract_v4.4"] == sha256(DEFAULT_CONTRACT_V44)
    contract = load_json(out / "scoring-contract-v4.5.proposed.json")
    assert contract["status"] == "draft_pending_human_signature"
    assert load_json(out / "claims-gate-v4.proposed.json")["status"] == (
        "draft_pending_human_signature"
    )
    with pytest.raises(DecisionError, match="refusing to overwrite"):
        main(["--plan", str(plan), "--apply", "--out", str(out)])


def test_frozen_artifacts_are_untouched() -> None:
    plan = load_json(DEFAULT_PLAN)
    assert sha256(DEFAULT_CONTRACT_V44) == plan["authority"]["contract_v4.4_signed"]["sha256"]
    assert sha256(DEFAULT_GATE_V3) == plan["authority"]["gate_v3_signed"]["sha256"]
    assert plan["authority"]["gate_v3_signed"]["sha256"] == (
        "b2b93b9ce46711b1e2f55d340c54452c1033eb15569f0dd865af9e3477d74fb3"
    )
    assert sha256(
        SCRATCH
        / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
    ) == ("ce1938b6d35a1292b22d8d75a3af461743e627ccebb0385f3267cb652fcd1650")
