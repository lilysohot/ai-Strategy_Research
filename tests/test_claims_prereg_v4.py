"""104-号 v4 amendment invariants: `unbound_union` leaves the stage-2 gate, becomes a diagnostic.

The amendment was decided by U on 2026-10-14 after the 101-号 replay showed the proxy cannot reach
its pre-registered ≤ 27 and — worse — measures annotation coverage rather than precision. These
tests pin the properties that keep the amendment honest:

* the v4 draft differs from the signed 99-号 body by exactly this one amendment, nothing else;
* every frozen value survives verbatim (tier lines, reading axes, guardrails, proxies, budget form);
* the diagnostic keeps its baseline (54) and its predicate; only the gate is gone;
* the 101-号 target reading (`≤ 27`, `unbound_union_passed: false`) is superseded by *registration*,
  not by editing bytes;
* the signer-facing path is fail-closed: the applier refuses an unsigned instrument and the v4
  stage-2 entry refuses to run without an effective record.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tools.check_claims_gate import sha256

SCRATCH = Path(__file__).resolve().parents[1] / ".scratch/claims-r2-role-isolation"
HERE = SCRATCH / "evidence/104-claims-prereg-v4-amendment-20261014/r0-zero-call"
PROPOSED = HERE / "claims-preregistration-v4.proposed.json"
SIGNOFF_MD = HERE / "claims-preregistration-v4-signoff.md"
MANIFEST = HERE / "MANIFEST.json"
GENERATOR = HERE / "build_prereg_v4_proposal.py"
APPLIER = HERE / "apply_prereg_v4_signoff.py"
ENTRY = HERE / "stage2_under_v4.py"
SIGNED_99 = (
    SCRATCH
    / "evidence/99-claims-prereg-v3-signed-r2-20261014"
    / "r0-zero-call/claims-preregistration.json"
)
DRAFT_95 = SCRATCH / "evidence/95-claims-prereg-20261014/r0-zero-call/claims-preregistration.json"
LANDING_101 = (
    SCRATCH
    / "evidence/101-claims-treatment-t1t2t3-landing-20261014/r0-zero-call/treatment-landing-record.json"
)
GATE_V3 = SCRATCH / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
REFUSAL_97 = (
    SCRATCH
    / "evidence/97-claims-governance-refusal-20261014/r0-zero-call/claims-governance-refusal.json"
)
CONTRACT_V44 = (
    SCRATCH
    / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
)
WORKSHEET = (
    SCRATCH
    / "evidence/102-claims-treatment-engineering-20261014"
    / "r0-zero-call/build_treatment_adjudication_worksheet.py"
)

EXPECTED_CHANGED = {
    "status",
    "pre_registered_treatment_rules.coverage_rule",
    "pre_registered_treatment_rules.rules",
    "prior_record_readings",
    "revisions",
    "not_done",
}
EXPECTED_ADDED = {
    "amended_from",
    "downstream_followups",
    "exit_rules.early_stop_before_human_adjudication.report_only_proxies",
    "exit_rules.early_stop_before_human_adjudication.stage2_proxies_protocol",
}
EXPECTED_REMOVED = {
    "exit_rules.early_stop_before_human_adjudication.stage2_proxies.unbound_union",
}


def _prereg() -> dict:
    return json.loads(PROPOSED.read_text(encoding="utf-8"))


def _signed_99() -> dict:
    return json.loads(SIGNED_99.read_text(encoding="utf-8"))


def _body_of_99() -> dict:
    signed = _signed_99()
    return {
        k: v
        for k, v in signed.items()
        if k not in {"signed_from", "countersignature", "supersedes"}
    }


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_draft_diff_is_exactly_the_one_amendment() -> None:
    generator = _module("build_prereg_v4_proposal", GENERATOR)
    result = generator.build()  # fails closed on any drift or unplanned leaf
    assert set(result["diff"]["changed"]) == EXPECTED_CHANGED
    assert set(result["diff"]["added"]) == EXPECTED_ADDED
    assert set(result["diff"]["removed"]) == EXPECTED_REMOVED
    assert result["unexpected"] == {
        "unexpected_changed": [],
        "unexpected_added": [],
        "unexpected_removed": [],
    }


def test_amendment_points_at_the_signed_99_record() -> None:
    amended_from = _prereg()["amended_from"]
    assert amended_from["sha256"] == sha256(SIGNED_99)
    assert amended_from["status_at_amend"] == "frozen_before_execution"
    assert "U" in amended_from["decided_by"]
    revisions = _prereg()["revisions"]
    assert revisions[-1]["changed_after_signature"] is True
    assert revisions[-1]["old_hash_retained"].endswith("claims-preregistration.json")


def test_stage2_no_longer_gates_on_unbound_union_but_still_reports_it() -> None:
    early = _prereg()["exit_rules"]["early_stop_before_human_adjudication"]
    assert set(early["stage2_proxies"]) == {
        "role_external_candidates",
        "redundant_renderings",
        "unbound_fields_without_reason_code",
    }
    diagnostic = early["report_only_proxies"]["unbound_union"]
    assert diagnostic["baseline"] == 54, "基线计数不变——改的是用法，不是值"
    assert diagnostic["gating"] is False
    assert diagnostic["classification"] == "diagnostic"
    assert diagnostic["moved_from"] == "stage2_proxies"
    assert diagnostic["owner_treatment_rule"] == "T2_unbound_disposition"
    assert "标注覆盖率" in diagnostic["basis"]
    assert early["report_only_proxies"]["gating"] is False
    assert "unbound_union" in early["stage2_proxies_protocol"]


def test_t2_keeps_ownership_but_loses_its_gate() -> None:
    rules = {rule["id"]: rule for rule in _prereg()["pre_registered_treatment_rules"]["rules"]}
    assert sorted(rules) == [
        "T1_no_opinion",
        "T2_unbound_disposition",
        "T3_dedupe_tie_break",
        "T4_missing_field_must_be_labelled",
    ]
    assert rules["T2_unbound_disposition"]["stop_loss_gate"] is False
    assert "report_only_proxies" in rules["T2_unbound_disposition"]["gate_note"]
    assert rules["T2_unbound_disposition"]["verified_by"] == "unbound_union"
    coverage = _prereg()["pre_registered_treatment_rules"]["coverage_rule"]
    assert "stage2_proxies" in coverage and "对账" in coverage


def test_frozen_values_survive_the_amendment_verbatim() -> None:
    body = _body_of_99()
    draft = _prereg()
    assert draft["exit_rules"]["tiers"] == body["exit_rules"]["tiers"], "线值 0.80 / 0.60 不得动"
    assert draft["reading_axes"] == body["reading_axes"]
    assert (
        draft["metrics"]["guardrails_must_not_regress"]
        == body["metrics"]["guardrails_must_not_regress"]
    )
    assert (
        draft["metrics"]["treatment_definition_checks"]
        == body["metrics"]["treatment_definition_checks"]
    )
    assert draft["exit_rules"]["trial_validity"] == body["exit_rules"]["trial_validity"]
    assert draft["evidence_chain"]["proxies"] == body["evidence_chain"]["proxies"]
    assert draft["budget_request"] == body["budget_request"]
    assert draft["gold_and_caliber_freezes"] == body["gold_and_caliber_freezes"]
    # The three gates the amendment does NOT touch keep their exact signed text.
    early_new = draft["exit_rules"]["early_stop_before_human_adjudication"]["stage2_proxies"]
    early_old = body["exit_rules"]["early_stop_before_human_adjudication"]["stage2_proxies"]
    for name in (
        "role_external_candidates",
        "redundant_renderings",
        "unbound_fields_without_reason_code",
    ):
        assert early_new[name] == early_old[name]


def test_101_target_reading_is_superseded_by_registration_not_by_editing() -> None:
    readings = _prereg()["prior_record_readings"]
    assert len(readings) == 2
    entry = readings[1]
    assert entry["registration_id"] == "REG-101-UNBOUND-UNION-DIAGNOSTIC"
    assert entry["record_sha256"] == sha256(LANDING_101)
    assert "unbound_union" in entry["field"]
    assert "诊断读数" in entry["reading_in_force"]
    assert entry["supersedes"]["record_sha256"] == sha256(LANDING_101)
    assert any("字节" in line for line in entry["does_not_change"])
    landing = json.loads(LANDING_101.read_text(encoding="utf-8"))
    assert landing["replay"]["stage2_proxies"]["targets"]["unbound_union"] == "≤ 27", (
        "101 号字节必须原样保留（targets 行是当时语境的档案）"
    )


def test_frozen_records_are_untouched_by_this_amendment() -> None:
    assert sha256(SIGNED_99) == "a2d174407daa5a1b88ba9ca44e698cf4512a399b2a4895254d0a3ab4b57edf04"
    assert sha256(DRAFT_95) == "443df86f559f973efa7d43fa636390463b0a5538922f19d1ef9c452157c7c657"
    assert sha256(LANDING_101) == "79c93cd9bb6f6220d6a356db55117708dc4cd8ac58db83b8e7c2e9e790478b70"
    assert sha256(GATE_V3) == "b2b93b9ce46711b1e2f55d340c54452c1033eb15569f0dd865af9e3477d74fb3"
    assert sha256(REFUSAL_97) == "697aae8cbe5130f4e36d159a1897779a229a980f540e0322a77ab23c9560618d"
    assert (
        sha256(CONTRACT_V44) == "ce1938b6d35a1292b22d8d75a3af461743e627ccebb0385f3267cb652fcd1650"
    )


def test_draft_body_is_signed_by_a_named_instrument_and_the_signature_is_verbatim() -> None:
    assert _prereg()["status"] == "draft_pending_human_signature", "草案文件保持未签形态"
    text = SIGNOFF_MD.read_text(encoding="utf-8")
    signature = next(line for line in text.splitlines() if line.startswith("reviewer:"))
    assert "xyl" in signature and "2026-10-14" in signature, "U 已具名签署"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "draft_pending_human_signature"
    assert manifest["model_calls"] == 0
    assert manifest["amendment_diff"]["unexpected"] == {
        "unexpected_changed": [],
        "unexpected_added": [],
        "unexpected_removed": [],
    }
    # The effective record carries the same signature line verbatim and points at these bytes.
    signed = json.loads((HERE / "claims-preregistration-v4.json").read_text(encoding="utf-8"))
    block = signed["countersignature"]
    assert block["instrument"]["signature_line"] == signature.strip(), "签认行逐字照录（不归一化）"
    assert block["instrument"]["sha256"] == f"sha256:{sha256(SIGNOFF_MD)}"
    signed_manifest = json.loads((HERE / "MANIFEST-signed.json").read_text(encoding="utf-8"))
    assert signed_manifest["status"] == "signed"
    assert signed_manifest["outputs"]["claims-preregistration-v4.json"] == sha256(
        HERE / "claims-preregistration-v4.json"
    )


def test_applier_refuses_an_unsigned_instrument(tmp_path: Path) -> None:
    applier = _module("apply_prereg_v4_signoff", APPLIER)
    assert applier.DRAFT == PROPOSED
    saved = applier.INSTRUMENT
    blank = tmp_path / "blank-signoff.md"
    blank.write_text("## 签名\n\nreviewer:            adjudicator:            signed_on:\n")
    applier.INSTRUMENT = blank
    try:
        with pytest.raises(SystemExit, match="named-signed"):
            applier.build()
    finally:
        applier.INSTRUMENT = saved


def test_v4_effective_record_exists_and_is_the_amended_form() -> None:
    entry = _module("stage2_under_v4", ENTRY)
    active = entry.active_prereg()  # fail-closed checks: frozen, amends 99 号, no unbound_union gate
    assert active == entry.ACTIVE
    record = json.loads(active.read_text(encoding="utf-8"))
    assert record["status"] == "frozen_before_execution"
    assert record["signed_from"]["sha256"] == sha256(PROPOSED), "生效件签认的是被审过的草案字节"
    assert record["countersignature"]["reviewer"] == "xyl"
    assert record["amended_from"]["sha256"] == sha256(SIGNED_99)
    gates = record["exit_rules"]["early_stop_before_human_adjudication"]["stage2_proxies"]
    assert "unbound_union" not in gates
    diff = json.loads((HERE / "prereg-v4-signed-diff.json").read_text(encoding="utf-8"))
    assert diff["changed_leaf_paths"] == ["status"]
    assert diff["unexpected_changed"] == []
    assert diff["verdict"]["stage2_gates_in_force"] == [
        "redundant_renderings",
        "role_external_candidates",
        "unbound_fields_without_reason_code",
    ]


def test_v4_entry_still_refuses_when_the_effective_record_is_absent(tmp_path: Path) -> None:
    entry = _module("stage2_under_v4", ENTRY)
    assert entry.ACTIVE.exists()
    saved = entry.ACTIVE
    entry.ACTIVE = tmp_path / "absent-v4.json"
    try:
        with pytest.raises(SystemExit, match="v4 生效件不存在"):
            entry.active_prereg()
    finally:
        entry.ACTIVE = saved


def test_gate_behaviour_follows_the_amended_criteria_not_the_script() -> None:
    """The 102-号 engine reads rules from the pointed-at record: repoint it, behaviour changes.

    Using the v4 *draft* as the stand-in proves the mechanism (the engine has no hard-coded
    `unbound_union` gate); the signed 99-号 record blocks the same numbers.
    """
    worksheet = _module("build_treatment_adjudication_worksheet", WORKSHEET)
    measured = {
        "role_external_candidates": 0,
        "unbound_union": 52,
        "redundant_renderings": 0,
        "unbound_fields_without_reason_code": 0,
    }
    worksheet.SIGNED_PREREG = SIGNED_99
    assert worksheet.apply_signed_rules(measured)["passed"] is False, "99 号判据下 52 > 27 ⇒ 阻断"
    worksheet.SIGNED_PREREG = PROPOSED
    verdict = worksheet.apply_signed_rules(measured)
    assert verdict["passed"] is True, "v4 判据下 unbound_union 不再是闸门 ⇒ 放行"
    assert [item["proxy"] for item in verdict["verdicts"]] == [
        "role_external_candidates",
        "redundant_renderings",
        "unbound_fields_without_reason_code",
    ]
