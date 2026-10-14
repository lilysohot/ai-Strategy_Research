"""Claims pre-registration (95 号) invariants: thresholds fixed before the run, budget left blank.

The trial's outcome decides whether the claims role stays, so these tests pin the properties that
keep the reading honest:

* the three exit tiers are derived from the *signed* contract's threshold values and form an
  exhaustive partition, so no result can fall outside them;
* the primary metric's baseline is recomputed from the frozen pool, not copied;
* the zero-call early-stop proxies use the field-first (corrected) definitions, and the two
  corrections to the 83/84-号 records are recorded rather than quietly applied;
* the budget ceiling is not self-filled, and the fairness clause requires the treatment arm to
  cover every binding family the frozen audit names;
* the primary metric's numerator (matched + correct_extra) is written down, not just its
  denominator;
* every zero-call stop-loss proxy is owned by exactly one pre-registered treatment rule, and
  "did the treatment run" items are split out of the quality guardrails, so a missed filter voids
  the trial instead of reading as "tier C: claims are bad";
* the 91-号 release line is registered as an unconditional PASS once the accepted-records axis
  left the verdict, superseding (not editing) the 97-号 reading.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from tools.check_claims_gate import sha256
from tools.evidence_guard import artifact_state

SCRATCH = Path(__file__).resolve().parents[1] / ".scratch/claims-r2-role-isolation"
PREREG = SCRATCH / "evidence/95-claims-prereg-20261014/r0-zero-call/claims-preregistration.json"
GENERATOR = SCRATCH / "evidence/95-claims-prereg-20261014/r0-zero-call/build_preregistration.py"
MANIFEST = SCRATCH / "evidence/95-claims-prereg-20261014/r0-zero-call/MANIFEST.json"
SIGNOFF_MD = (
    SCRATCH / "evidence/95-claims-prereg-20261014/r0-zero-call/claims-preregistration-signoff.md"
)
SIGNED_98 = SCRATCH / "evidence/98-claims-prereg-v3-signed-20261014/r0-zero-call"
SIGNED_99 = SCRATCH / "evidence/99-claims-prereg-v3-signed-r2-20261014/r0-zero-call"
# The effective signed record: 98 号 pointed at the instrument before U corrected its date literal.
SIGNED_PREREG = SIGNED_99 / "claims-preregistration.json"
SIGNED_DIFF = SIGNED_99 / "prereg-signed-diff.json"
SIGNED_MANIFEST = SIGNED_99 / "MANIFEST.json"
CONTRACT_V44 = (
    SCRATCH
    / "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
)
GATE_V3 = SCRATCH / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
REFUSAL_97 = (
    SCRATCH
    / "evidence/97-claims-governance-refusal-20261014/r0-zero-call/claims-governance-refusal.json"
)
POOL = (
    SCRATCH
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
BINDING_AUDIT = (
    SCRATCH
    / "evidence/17-structured-extraction-convergence-closure-20261009/claims-binding-audit.json"
)


def _prereg() -> dict:
    return json.loads(PREREG.read_text(encoding="utf-8"))


def test_exit_tiers_are_derived_from_the_signed_thresholds() -> None:
    contract = json.loads(CONTRACT_V44.read_text(encoding="utf-8"))
    target = contract["claims_thresholds"]["target_line"]["candidate_precision_min"]
    release = contract["claims_thresholds"]["release_line_proposed"]["candidate_precision_min"]
    tiers = _prereg()["exit_rules"]["tiers"]
    assert [tier["id"] for tier in tiers] == [
        "A_keep_and_pass_target",
        "B_conditional_keep",
        "C_drop_from_default_path",
    ]
    assert f"precision ≥ {target}" in tiers[0]["condition"]
    assert f"{release} ≤ precision < {target}" in tiers[1]["condition"]
    assert f"precision < {release}" in tiers[2]["condition"]
    # Exhaustive: A and B demand the full guardrail set, C is the complement of A∪B.
    for tier in tiers[:2]:
        assert "target_recall = 20/20" in tier["condition"]
        assert "unresolved = 0" in tier["condition"]
        assert "哨兵 3/3" in tier["condition"]
    assert "或" in tiers[2]["condition"]


def test_primary_baseline_is_recomputed_not_declared() -> None:
    evidence = _prereg()["evidence_chain"]["baseline_calibers"]
    assert evidence["D2_in_role_only"] == "51/81 = 0.6296"
    assert evidence["target_recall"] == "20/20 = 1.0000"
    pool = json.loads(POOL.read_text(encoding="utf-8"))["adjudications"]
    assert len(pool) == 110
    assert evidence["D1_all_candidates"] == "56/110 = 0.5091"


def test_primary_numerator_is_defined_and_matches_the_frozen_ledger() -> None:
    primary = _prereg()["metrics"]["primary"]
    assert primary["numerator"] == "matched + correct_extra"
    assert "duplicate" in primary["denominator"], "分母含 duplicate（已签 C2 单一口径）"
    basis = primary["numerator_basis"]
    assert "claims_precision_single_source" in basis
    assert "correct_extra 属分子" in basis, (
        "分子定义必须与已签 C2 同源，不许把 correct_extra 挪进分母"
    )
    counterfactual = _prereg()["deterministic_ceiling_on_frozen_pool"]["counterfactuals"]
    judgements = counterfactual["D2_baseline"]["judgements"]
    numerator = judgements["matched"] + judgements["correct_extra"]
    denominator = numerator + judgements["incorrect"] + judgements["duplicate"]
    assert f"{numerator}/{denominator}" in primary["worked_example_on_frozen_pool"]
    assert primary["baseline"] == f"{numerator}/{denominator} = 0.6296"


def test_treatment_definition_items_are_split_out_of_the_quality_guardrails() -> None:
    metrics = _prereg()["metrics"]
    guardrails = metrics["guardrails_must_not_regress"]
    # role_external_candidates is how *the treatment* is defined; reading it as a quality guardrail
    # turns a missed filter into "tier C: claims are bad".
    assert "role_external_candidates" not in guardrails
    assert guardrails["items"] == ["target_recall", "unresolved_candidates", "sentinels"]
    treatment_defs = metrics["treatment_definition_checks"]
    assert [item["proxy"] for item in treatment_defs["items"]] == [
        "role_external_candidates",
        "unbound_fields_without_reason_code",
    ]
    assert all(item["rule"] == "== 0" for item in treatment_defs["items"])
    trial_validity = _prereg()["exit_rules"]["trial_validity"]
    assert len(trial_validity["checks"]) == 2
    assert "无效" in trial_validity["if_failed"] and "不计入去留" in trial_validity["if_failed"]
    for tier in _prereg()["exit_rules"]["tiers"]:
        assert "质量护栏" in tier["condition"]
        assert "角色外" not in tier["condition"]
    forbidden = " ".join(_prereg()["exit_rules"]["forbidden_readings"])
    assert "C 档" in forbidden


def test_proxies_union_their_two_definitions() -> None:
    proxies = _prereg()["evidence_chain"]["proxies"]
    assert proxies["unbound_by_field"] == 25
    assert proxies["unbound_by_reason_code"] == 45
    assert proxies["unbound_union"] == 54
    # The union is at least each part and at most their sum; the gap is the unlabelled set.
    assert (
        max(proxies["unbound_by_field"], proxies["unbound_by_reason_code"])
        <= proxies["unbound_union"]
    )
    assert (
        proxies["unbound_union"] <= proxies["unbound_by_field"] + proxies["unbound_by_reason_code"]
    )
    assert proxies["unbound_fields_without_reason_code"] > 0, (
        "reason 码漏标是本件更正的核心事实，若为 0 说明定义被改回去了"
    )


def test_redundancy_is_grouped_by_quote_not_by_value() -> None:
    proxies = _prereg()["evidence_chain"]["proxies"]
    assert proxies["redundant_renderings"] == len(proxies["redundant_groups"]) == 2
    assert any("gpuasic机柜" in group for group in proxies["redundant_groups"])


def test_early_stop_proxies_are_pre_registered() -> None:
    stage2 = _prereg()["exit_rules"]["early_stop_before_human_adjudication"]["stage2_proxies"]
    assert stage2["role_external_candidates"]["rule"].startswith("== 0")
    assert stage2["unbound_union"]["rule"] == "≤ baseline × 0.5"
    assert stage2["redundant_renderings"]["rule"] == "== 0"
    assert stage2["unbound_fields_without_reason_code"]["rule"] == "== 0"


def test_prior_record_corrections_are_recorded() -> None:
    corrections = _prereg()["corrections_to_prior_records"]
    retracted = [entry for entry in corrections if entry.get("retracted")]
    assert len(retracted) == 1
    text = json.dumps(retracted[0], ensure_ascii=False)
    assert "目标价" in text, "被撤回的原断言必须逐字可查"
    assert "未被标任何坐标 reason 码" in text
    consequences = " ".join(retracted[0]["consequences"])
    assert "9 条" in consequences


def test_budget_ceiling_is_not_self_filled() -> None:
    request = _prereg()["budget_request"]
    assert request["stage_1_live_run"]["requested_ceiling"] is None
    assert request["stage_1_live_run"]["filled_by"] == "U"
    assert request["stage_2_proxy_check"]["requested"] == 0
    assert (
        "human_adjudication" in request["stage_3_human_adjudication"]["shape"]
        or (request["stage_3_human_adjudication"]["shape"])
    )
    blocked = json.loads(MANIFEST.read_text(encoding="utf-8"))["blocked_on"]
    assert any("requested_ceiling" in entry for entry in blocked)


def test_fairness_clause_covers_every_binding_family() -> None:
    audit = json.loads(BINDING_AUDIT.read_text(encoding="utf-8"))
    families = {
        key: value
        for key, value in audit["incorrect_candidate_failure_families"].items()
        if isinstance(value, int)
    }
    required = _prereg()["binding_caveat"]["required_treatment_coverage"]
    assert sorted(required) == sorted(families)
    assert any("metric" in name for name in required)
    assert any("subject" in name for name in required)


def test_gold_and_calibers_are_frozen_in_the_record() -> None:
    freezes = _prereg()["gold_and_caliber_freezes"]
    assert freezes["gold"]["claims_targets"] == 20
    assert freezes["gold"]["sha256"] == sha256(
        SCRATCH / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
    )
    assert freezes["thresholds_in_force"]["target_line"]["candidate_precision_min"] == 0.8
    preconditions = freezes["governance_preconditions"]
    assert preconditions["M3"] == "不需要：与去留无关"
    assert "字面等价" in preconditions["M1"], "M1 必须带着退化证明被移出读数轴"
    assert len(preconditions["only_prerequisites"]) == 3


def test_reading_axes_are_four_and_the_excluded_axis_is_proved_degenerate() -> None:
    axes = _prereg()["reading_axes"]
    assert axes["in_verdict"] == [
        "candidate_precision",
        "target_recall",
        "unresolved_candidates",
        "sentinels",
    ]
    assert sorted(axes["excluded"]) == [
        "accepted_records_per_source_min",
        "accepted_records_total_min",
        "per_source_precision",
    ]
    assert "floor(0.85×20)=17" in axes["excluded"]["accepted_records_total_min"]
    assert "零独立判别力" in axes["excluded"]["accepted_records_total_min"]


def test_deterministic_ceiling_is_measured_before_the_run() -> None:
    ceiling = _prereg()["deterministic_ceiling_on_frozen_pool"]
    assert ceiling["safe_ceiling"] == "51/79 = 0.6456"
    assert ceiling["over_guardrail_ceiling"] == "39/55 = 0.7091"
    variants = ceiling["counterfactuals"]
    assert variants["D2_baseline"]["precision"] == "51/81 = 0.6296"
    for name in ("reject_unbound", "reject_unbound_plus_dedupe"):
        assert variants[name]["recall"] == "19/20", "破护栏的变体必须如实登记召回损失"


def test_treatment_rules_are_pre_registered_with_their_forced_choices() -> None:
    rules = {rule["id"]: rule for rule in _prereg()["pre_registered_treatment_rules"]["rules"]}
    assert sorted(rules) == [
        "T1_no_opinion",
        "T2_unbound_disposition",
        "T3_dedupe_tie_break",
        "T4_missing_field_must_be_labelled",
    ]
    assert rules["T1_no_opinion"]["score_effect_on_frozen_pool"].startswith("0")
    assert "NT-C17" in rules["T2_unbound_disposition"]["forced_by_measurement"]
    assert "补齐" in rules["T2_unbound_disposition"]["rule"]
    assert "禁止使用金标" in rules["T3_dedupe_tie_break"]["rule"]
    load_bearing = rules["T3_dedupe_tie_break"]["load_bearing"]
    assert any("归母净利润" in entry["group"] for entry in load_bearing)
    assert any(
        member["judgement"] == "matched" for entry in load_bearing for member in entry["members"]
    )


def test_every_stop_loss_proxy_is_owned_by_a_treatment_rule() -> None:
    prereg = _prereg()
    rules = {rule["id"]: rule for rule in prereg["pre_registered_treatment_rules"]["rules"]}
    stage2 = prereg["exit_rules"]["early_stop_before_human_adjudication"]["stage2_proxies"]
    owners = {name: entry["owner_treatment_rule"] for name, entry in stage2.items()}
    # A stop-loss that no treatment rule can move aborts the run whatever the repair did (the reason
    # T4 exists: reason-code under-labelling had no owner).
    assert sorted(owners.values()) == sorted(rules), "止损项与治疗规则必须一一对账"
    assert len(set(owners.values())) == len(owners)
    for name, owner in owners.items():
        assert rules[owner]["verified_by"] == name
    reason_code_item = stage2["unbound_fields_without_reason_code"]
    assert reason_code_item["classification"] == "treatment_definition"
    assert "reason 码" in rules["T4_missing_field_must_be_labelled"]["rule"]
    protocol = prereg["pre_registered_treatment_rules"]["coverage_rule"]
    assert "不得起跑" in protocol


def test_91_release_line_is_registered_as_unconditional_pass() -> None:
    readings = _prereg()["prior_record_readings"]
    assert len(readings) == 1
    entry = readings[0]
    assert entry["field"] == "verdict.release_line.precondition"
    assert "无条件 PASS" in entry["reading_in_force"]
    assert "D-1" in entry["recorded_text"], "被改读法的原文必须逐字可查"
    superseded = entry["supersedes"]
    assert superseded["field"] == "consequences[3]"
    assert "pending_caliber" in superseded["superseded_text"]
    assert entry["record_sha256"] == sha256(GATE_V3)
    assert superseded["record_sha256"] == sha256(REFUSAL_97)
    assert any("字节" in line for line in entry["does_not_change"]), "只改读法、不改记录"
    assert "无条件 PASS" in _prereg()["reading_axes"]["precondition_note"]


def test_v2_and_v3_revisions_record_what_changed_and_what_is_frozen() -> None:
    revisions = _prereg()["revisions"]
    assert [entry["revision"].split("（")[0] for entry in revisions] == ["v1 → v2", "v2 → v3"]
    for revision in revisions:
        assert revision["no_signature_existed_before"] is True, (
            "草案态才允许就地改；已签件不得这样做"
        )
        assert "0.80 / 0.60" in " ".join(revision["unchanged"]), "线值不得随编辑变动"
    assert "reading_axes" in " ".join(revisions[0]["changes"])
    v3 = " ".join(revisions[1]["changes"])
    for expected in (
        "prior_record_readings",
        "T4_missing_field_must_be_labelled",
        "trial_validity",
    ):
        assert expected in v3


def test_recorded_counterfactuals_are_recomputable_from_the_frozen_pool() -> None:
    spec = importlib.util.spec_from_file_location("build_preregistration", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    recomputed = module.measure_treatment_counterfactuals(pool, 20)
    recorded = _prereg()["evidence_chain"]["treatment_counterfactuals"]
    assert recomputed["variants"] == recorded["variants"]
    assert recomputed["reject_unbound_loses_matched_gold"] == ["NT-C17"]
    assert recomputed["dedupe_groups"] == recorded["dedupe_groups"]


def test_frozen_artifacts_are_untouched_by_this_record() -> None:
    assert sha256(GATE_V3) == "b2b93b9ce46711b1e2f55d340c54452c1033eb15569f0dd865af9e3477d74fb3"
    assert (
        sha256(REFUSAL_97) == "697aae8cbe5130f4e36d159a1897779a229a980f540e0322a77ab23c9560618d"
    ), "95 号只登记对 97 号读法的取代，不改其字节"
    assert (
        sha256(CONTRACT_V44) == "ce1938b6d35a1292b22d8d75a3af461743e627ccebb0385f3267cb652fcd1650"
    )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["model_calls"] == 0
    assert any("10-quality-gold-freeze" in entry for entry in manifest["does_not_touch"])


def test_signed_record_equals_the_draft_plus_the_signoff_only() -> None:
    draft = _prereg()
    assert draft["status"] == "draft_pending_human_signature", "草案件本身保持未签形态"
    signed = json.loads(SIGNED_PREREG.read_text(encoding="utf-8"))
    assert signed["status"] == "frozen_before_execution"
    assert signed["signed_from"]["sha256"] == sha256(PREREG), "签认的是被审过的那份草案字节"
    body = {
        k: v
        for k, v in signed.items()
        if k not in {"status", "signed_from", "countersignature", "supersedes"}
    }
    assert body == {k: v for k, v in draft.items() if k != "status"}, "正文不得被签认步骤顺手改写"
    assert artifact_state(SIGNED_PREREG) == "signed"


def test_relanded_record_supersedes_98_without_editing_it() -> None:
    archived = SIGNED_98 / "claims-preregistration.json"
    assert sha256(archived) == "0cfefc79f6adaa99f640a7cd70038bb903d5e49cc6213fd4462b81a5f8e639c0", (
        "98 号是更正前签认面的旧哈希档案，不得改写"
    )
    signed = json.loads(SIGNED_PREREG.read_text(encoding="utf-8"))
    assert signed["supersedes"]["sha256"] == sha256(archived)
    assert signed["supersedes"]["status_at_supersede"] == "signed"
    still_there = json.loads(archived.read_text(encoding="utf-8"))
    assert still_there["countersignature"]["signed_on"] == "2026-10=14", "旧记录保持原样"
    manifest = json.loads(SIGNED_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["supersedes"]["sha256"] == sha256(archived)


def test_signed_record_keeps_the_signature_verbatim_and_registers_the_correction() -> None:
    block = json.loads(SIGNED_PREREG.read_text(encoding="utf-8"))["countersignature"]
    instrument = block["instrument"]
    assert instrument["sha256"] == f"sha256:{sha256(SIGNOFF_MD)}", "签认件哈希必须指向现行文面"
    assert instrument["signature_line"] in SIGNOFF_MD.read_text(encoding="utf-8")
    assert block["reviewer"] == block["adjudicator"] == "xyl"
    assert block["signed_on"] == "2026-10-14"
    revision = instrument["revision"]
    # The pre-correction instrument (date literal '2026-10=14') stays traceable through this record.
    assert revision["pre_correction_signed_on_literal"] == "2026-10=14"
    assert revision["pre_correction_sha256"] == (
        "sha256:c569c07327e6e39043f7798b5d9207ba38ed4ed1a872f51f043456fa687bfc6b"
    )
    assert revision["corrected_by"] == "U" and revision["signer_unchanged"] is True
    assert "预算" in " ".join(block["does_not_cover"])


def test_signed_diff_record_has_no_unexpected_leaves_and_is_not_runnable() -> None:
    diff = json.loads(SIGNED_DIFF.read_text(encoding="utf-8"))
    assert diff["changed_leaf_paths"] == ["status"]
    assert diff["added_leaf_paths"] == ["countersignature", "signed_from", "supersedes"]
    assert diff["removed_leaf_paths"] == []
    assert diff["unexpected_changed"] == []
    assert diff["unexpected_added"] == []
    assert diff["unexpected_removed"] == []
    assert diff["instrument_revision"]["signed_on_literal_now"] == "2026-10-14"
    assert diff["verdict"]["runnable"] is False, "预算 ceiling 未填 ⇒ 签认不等于可起跑"
    assert diff["verdict"]["budget_ceiling"] is None
    assert diff["verdict"]["treatments_in_force"][-1] == "T4_missing_field_must_be_labelled"
    manifest = json.loads(SIGNED_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "signed" and manifest["model_calls"] == 0
    assert any("requested_ceiling" in entry for entry in manifest["blocked_on"])
    assert any("95-claims-prereg" in entry for entry in manifest["does_not_touch"])
    assert any("98-claims-prereg" in entry for entry in manifest["does_not_touch"])
