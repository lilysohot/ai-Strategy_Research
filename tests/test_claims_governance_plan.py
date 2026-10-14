"""Claims governance plan (93 号) invariants: carrier cells stay blank, corrections stay bound.

These tests pin the properties the governance layer must keep, so the "same concept returns every
round" failure mode cannot come back silently:

* the three cells (M1/M2/M3) are carrier meta-rules, not values: ``value`` is null, the status is
  pending, and every registration field R1-R4 requires is present;
* a correction registration binds the *artifact hash* it excuses, and an unsigned registration
  cannot excuse anything (the checker's own author must not grant themselves an exception);
* the block/escalation behaviour of ``pass-not-dependent-on-unfrozen-axis``: report-only while the
  R1/R2 rules are unsigned, blocking once they are signed;
* the plan's recorded frozen-input hashes still match disk, so the plan cannot outlive its inputs.

They read the real artifacts under ``.scratch/claims-r2-role-isolation`` (same convention as
``tests/test_claims_gate_invariants.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.check_claims_gate import (
    DEFAULT_GOVERNANCE_CORRECTIONS,
    DEFAULT_GOVERNANCE_PLAN,
    Inputs,
    load_json,
    run_checks,
    sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"
GATE_V3 = SCRATCH / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
PLAN = (
    SCRATCH / "evidence/93-claims-governance-plan-20261014/r0-zero-call/claims-governance-plan.json"
)
TEMPLATE = (
    SCRATCH
    / "evidence/93-claims-governance-plan-20261014/r0-zero-call"
    / "governance-registration-template.json"
)
CHECK_ID = "pass-not-dependent-on-unfrozen-axis"


def _by_id(checks: list, check_id: str):
    matches = [c for c in checks if c.check_id == check_id]
    assert matches, f"check {check_id} missing"
    return matches[0]


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _mutated_gate(tmp_path: Path) -> Path:
    """Same defect, different bytes: the registered correction must no longer cover it."""
    gate = load_json(GATE_V3)
    gate["verdict"]["release_line"]["_mutated_for_test"] = True
    return _write(tmp_path / "claims-gate-mutated.json", gate)


# ------------------------------------------------------------------ cells (M1-M3)


def test_cells_are_pending_carrier_questions_with_no_value() -> None:
    plan = load_json(PLAN)
    assert plan["status"] == "draft_pending_human_signature"
    cells = {cell["id"]: cell for cell in plan["cells"]}
    assert sorted(cells) == ["M1", "M2", "M3"]
    for cell in cells.values():
        assert cell["kind"] == "carrier_meta_rule"
        assert cell["value"] is None, "治理层不得预填取值"
        assert cell["status"] == "pending_human_decision"
        assert cell["pending_caliber"] is True
        assert cell["owner"] == "U"
        assert cell["recompute_on_fill"], "R3: 裁完后必须重算的结论路径不可为空"
        assert len(cell["options"]) >= 2
        for option in cell["options"]:
            assert option["measured"], "每个选项必须附实测后果，不得只给推荐值"
        assert cell["reopen_history"], "须登记该概念此前以什么名字出现过"


def test_cells_cover_every_axis_the_gate_leaves_unfrozen() -> None:
    gate = load_json(GATE_V3)
    plan = load_json(PLAN)
    axes = set(gate["unfrozen_axes"])
    m1 = next(cell for cell in plan["cells"] if cell["id"] == "M1")
    m2 = next(cell for cell in plan["cells"] if cell["id"] == "M2")
    assert axes == {
        "accepted_records_total_min",
        "accepted_records_per_source_min",
        "per_source_precision_axis",
    }
    for axis in ("accepted_records_total_min", "accepted_records_per_source_min"):
        assert axis in m1["applies_to"]
    assert m2["applies_to"] == ["per_source_precision_axis"]


def test_m3_axes_match_the_signed_use_grading_axes() -> None:
    contract = load_json(
        SCRATCH
        / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
    )
    planned = next(cell for cell in load_json(PLAN)["cells"] if cell["id"] == "M3")
    for axis in ("attribution", "perspective", "source_stance"):
        assert axis in contract["claims_use_grading"]["axes"]
        assert any(axis in entry for entry in planned["applies_to"])
    assert planned["measured_common"]["records_that_can_compare_or_calculate_today"] == "11/56"


# ------------------------------------------------------------------ measurement


def test_measured_accepted_counts_match_the_frozen_pool() -> None:
    plan = load_json(PLAN)["verification"]["measured_by_this_script"]
    pool = load_json(Inputs().pool)
    matched = [row for row in pool["adjudications"] if row.get("judgement") == "matched"]
    assert plan["accepted_records_total"] == len(matched) == 20
    assert plan["accepted_records_per_source"] == {"f16e7fde9553": 10, "dca4bad7f85b": 10}
    gate = load_json(GATE_V3)
    assert plan["gate_v3_unfrozen_axes"] == gate["unfrozen_axes"]
    assert plan["gate_v3_release_precondition"] == gate["verdict"]["release_line"]["precondition"]


def test_plan_recorded_frozen_input_hashes_still_match_disk() -> None:
    recorded = load_json(PLAN)["verification"]["frozen_input_hashes"]
    assert recorded, "plan must pin the bytes it read"
    for name, digest in recorded.items():
        assert digest == sha256(_input_path_for(name)), f"{name} drifted after the plan was written"


def _input_path_for(name: str) -> Path:
    mapping = {
        "frozen_gold": SCRATCH / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json",
        "p1r5_candidate_adjudications_signed": (
            SCRATCH
            / "evidence/17-structured-extraction-convergence-closure-20261009"
            / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
        ),
        "scoring_contract_v4.3": (
            SCRATCH / "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json"
        ),
        "items_gate_v3_signed_reference": (
            SCRATCH / "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"
        ),
        "signed_scoring_contract_v4.4": (
            SCRATCH
            / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
        ),
        "claims_gate_v3_signed": GATE_V3,
        "claims_scope_registration": (
            SCRATCH
            / "evidence/92-claims-scope-registration-20261014/r0-zero-call/claims-scope-registration.json"
        ),
    }
    return mapping[name]


# ------------------------------------------------------------------ corrections


def test_correction_binds_the_signed_gate_hash_and_field() -> None:
    corrections = load_json(DEFAULT_GOVERNANCE_CORRECTIONS)
    entry = corrections["corrections"][0]
    assert entry["id"] == "CORR-91-PRECONDITION"
    assert entry["artifact"]["sha256"] == sha256(GATE_V3)
    assert entry["field_path"] == ["verdict", "release_line"]
    assert entry["artifact"]["bytes_unchanged"] is True
    assert entry["status"] != "signed", "本件未签认；豁免不得自授"


def test_unsigned_registration_cannot_excuse_a_finding() -> None:
    """The checker's own author must not be able to grant the exception by writing it."""
    checks = run_checks(Inputs())
    check = _by_id(checks, CHECK_ID)
    assert check.verdict == "note", "规则未签认 ⇒ 只检出，不阻塞，也不得记为通过"
    assert check.blocking is False
    assert check.actual["uncovered_lines"] == ["release_line"]
    assert check.actual["rules_in_force"] is False
    assert check.actual["pass_lines_with_precondition"]["release_line"]["honored"] is False


def test_dependency_is_detected_from_the_real_gate() -> None:
    check = _by_id(run_checks(Inputs()), CHECK_ID)
    declared = check.actual["pass_lines_with_precondition"]["release_line"]["declared"]
    assert declared["precondition"].startswith("D-1 ≠ a")
    assert check.actual["unfrozen_axes"][:3] == [
        "accepted_records_total_min",
        "accepted_records_per_source_min",
        "per_source_precision_axis",
    ]


def test_unregistered_dependency_fails_closed_once_the_rule_is_in_force(tmp_path: Path) -> None:
    signed_plan = load_json(DEFAULT_GOVERNANCE_PLAN)
    signed_plan["rules_in_force"]["status"] = "signed"
    plan_path = _write(tmp_path / "claims-governance-plan-signed.json", signed_plan)
    gate = _mutated_gate(tmp_path)

    checks = run_checks(Inputs(gate=gate, governance_plan=plan_path))
    check = _by_id(checks, CHECK_ID)
    assert check.verdict == "fail"
    assert check.blocking is True

    # Reported only while the rule is not yet in force -- governance must not freeze an artifact
    # on the strength of an unsigned rule.
    reported = _by_id(run_checks(Inputs(gate=gate)), CHECK_ID)
    assert reported.verdict == "note"
    assert reported.blocking is False


def test_signed_registration_excuses_only_its_own_artifact(tmp_path: Path) -> None:
    signed = load_json(DEFAULT_GOVERNANCE_CORRECTIONS)
    signed["corrections"][0]["status"] = "signed"
    corrections_path = _write(tmp_path / "governance-corrections-signed.json", signed)
    signed_plan = load_json(DEFAULT_GOVERNANCE_PLAN)
    signed_plan["rules_in_force"]["status"] = "signed"
    plan_path = _write(tmp_path / "claims-governance-plan-signed.json", signed_plan)

    covered = _by_id(
        run_checks(Inputs(governance_plan=plan_path, governance_corrections=corrections_path)),
        CHECK_ID,
    )
    assert covered.verdict == "pass"
    assert covered.actual["pass_lines_with_precondition"]["release_line"]["honored"] is True

    other = _by_id(
        run_checks(
            Inputs(
                gate=_mutated_gate(tmp_path),
                governance_plan=plan_path,
                governance_corrections=corrections_path,
            )
        ),
        CHECK_ID,
    )
    assert other.verdict == "fail", "登记只豁免它绑定的那份产物字节"


# ------------------------------------------------------------------ template / pointer


def test_registration_template_forbids_prefilled_values() -> None:
    template = load_json(TEMPLATE)
    fields = template["fields"]
    for required in (
        "status",
        "value",
        "owner",
        "decide_by",
        "pending_caliber",
        "recompute_on_fill",
        "measured_options",
    ):
        assert fields[required]["required"] is True
    assert fields["status"]["allowed"] == [
        "pending_human_decision",
        "decided",
        "expired_to_report_only",
    ]
    forbidden = " ".join(template["forbidden"])
    assert "预填 value" in forbidden
    assert "PASS" in forbidden
    assert "自动放行" in forbidden


def test_plan_checker_pointer_resolves_to_a_real_check() -> None:
    pointer = load_json(DEFAULT_GOVERNANCE_PLAN)["rules_in_force"]["checker"]
    assert pointer.endswith(CHECK_ID)
    assert _by_id(run_checks(Inputs()), CHECK_ID).check_id == CHECK_ID
