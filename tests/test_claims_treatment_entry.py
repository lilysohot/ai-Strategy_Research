"""The claims treatment arm's entry pair (102 号): freeze, gates, stage 2, worksheet.

What these tests pin, all zero-call:

* the executor refuses unless the *signed* pre-registration is frozen, names the four treatment rules
  and carries a filled ceiling — "未填预算不得起跑" is enforced by code, not by convention;
* the stop-loss rules are read from the signed file and evaluated literally (``== 0`` /
  ``≤ baseline × 0.5``), so amending the signed rule changes behaviour without a code edit;
* stage 2 measures the new pool with the same predicates as 95 号 (field-first union, redundancy by
  subject+metric+quote+kind);
* the landed freeze is fail-closed: ``runnable=false`` while the ceiling is empty, per-run ceilings
  copied from the signed budget reference, and version fingerprints recording the landed treatment.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / ".scratch/claims-r2-role-isolation/evidence/102-claims-treatment-engineering-20261014"
HERE = PKG / "r0-zero-call"
SIGNED_PREREG = (
    ROOT
    / ".scratch/claims-r2-role-isolation/evidence/99-claims-prereg-v3-signed-r2-20261014"
    / "r0-zero-call/claims-preregistration.json"
)
FREEZE = HERE / "claims-treatment-plan-freeze"


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prereg_copy(tmp_path: Path, **changes: object) -> Path:
    payload = json.loads(SIGNED_PREREG.read_text(encoding="utf-8"))
    payload.update(changes)
    if "budget" in changes:
        payload["budget_request"]["stage_1_live_run"].update(changes["budget"])  # type: ignore[arg-type]
        payload["budget_request"]["stage_1_live_run"].pop("budget", None)
    target = tmp_path / "prereg.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def test_executor_refuses_without_a_filled_ceiling(tmp_path: Path) -> None:
    executor = _module("execute_claims_treatment")
    executor.SIGNED_PREREG = _prereg_copy(tmp_path)  # signed copy keeps requested_ceiling: null
    executor.BUDGET_AUTHORISATION = tmp_path / "absent-authorisation.json"
    with pytest.raises(SystemExit, match="未填"):
        executor.authorised_budget()


def test_executor_reads_the_authorised_budget_from_the_103_record() -> None:
    executor = _module("execute_claims_treatment")
    budget = executor.authorised_budget()
    assert budget["value"] == 1_000_000
    assert budget["unit"] == "tokens"
    assert budget["stated_by"] == "U"
    assert "103-claims-budget-authorisation" in budget["source"]
    assert budget["per_run"]["claims-industrial-fulian"] == 10
    assert budget["per_run"]["claims-optical-module"] == 14


def test_executor_refuses_an_authorisation_for_another_preregistration(tmp_path: Path) -> None:
    executor = _module("execute_claims_treatment")
    authorisation = json.loads(executor.BUDGET_AUTHORISATION.read_text(encoding="utf-8"))
    authorisation["signed_prereg"]["sha256"] = "0" * 64
    executor.BUDGET_AUTHORISATION = tmp_path / "authorisation.json"
    executor.BUDGET_AUTHORISATION.write_text(
        json.dumps(authorisation, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="different pre-registration"):
        executor.authorised_budget()


def test_executor_falls_back_to_a_filled_signed_leaf(tmp_path: Path) -> None:
    executor = _module("execute_claims_treatment")
    executor.SIGNED_PREREG = _prereg_copy(tmp_path)
    executor.BUDGET_AUTHORISATION = tmp_path / "absent-authorisation.json"
    payload = json.loads(executor.SIGNED_PREREG.read_text(encoding="utf-8"))
    payload["budget_request"]["stage_1_live_run"]["requested_ceiling"] = 24
    executor.SIGNED_PREREG.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert executor.authorised_budget()["value"] == 24


def test_token_accounting_reads_the_ledger_usage(tmp_path: Path) -> None:
    import sqlite3

    executor = _module("execute_claims_treatment")
    store = tmp_path / "run-a/live-store/index"
    store.mkdir(parents=True)
    connection = sqlite3.connect(store / "structured.sqlite3")
    connection.execute("CREATE TABLE attempts (usage TEXT)")
    connection.executemany(
        "INSERT INTO attempts VALUES (?)",
        [('{"total_tokens": 4698}',), ('{"total_tokens": 4798}',), (None,)],
    )
    connection.commit()
    connection.close()
    usage = executor.tokens_used(tmp_path, ["run-a", "run-b"])
    assert usage["per_run"] == {"run-a": 9496}
    assert usage["total_tokens"] == 9496


def test_landed_budget_authorisation_leaves_the_signed_record_untouched() -> None:
    authorisation = json.loads(
        (
            ROOT
            / ".scratch/claims-r2-role-isolation/evidence/103-claims-budget-authorisation-20261014"
            / "r0-zero-call/budget-authorisation.json"
        ).read_text(encoding="utf-8")
    )
    signed = json.loads(SIGNED_PREREG.read_text(encoding="utf-8"))
    assert authorisation["budget"]["ceiling_value"] == 1_000_000
    assert authorisation["budget"]["ceiling_unit"] == "tokens"
    assert authorisation["signed_prereg"]["sha256"] != ""
    assert authorisation["signed_prereg"]["leaf_state_in_signed_record"] is None
    assert signed["status"] == "frozen_before_execution"
    assert signed["budget_request"]["stage_1_live_run"]["requested_ceiling"] is None, (
        "已签件的那一格必须保持空白：预算落在 103 号，不写回 99 号"
    )
    reference = {
        str(item["name"]): int(item["attempt_ceiling"])
        for item in signed["budget_request"]["stage_1_live_run"]["historical_reference"][
            "per_execution"
        ]
    }
    for name, ceiling in reference.items():
        assert authorisation["per_run_attempt_ceilings"][name] == ceiling


def test_executor_refuses_unsigned_or_retooled_preregistrations(tmp_path: Path) -> None:
    executor = _module("execute_claims_treatment")
    executor.SIGNED_PREREG = _prereg_copy(tmp_path, status="draft_pending_human_signature")
    with pytest.raises(SystemExit, match="refusing to run"):
        executor.authorised_budget()

    payload = json.loads(SIGNED_PREREG.read_text(encoding="utf-8"))
    payload["pre_registered_treatment_rules"]["rules"] = [
        rule
        for rule in payload["pre_registered_treatment_rules"]["rules"]
        if rule["id"] != "T4_missing_field_must_be_labelled"
    ]
    executor.SIGNED_PREREG = tmp_path / "prereg.json"
    executor.SIGNED_PREREG.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="treatment rules"):
        executor.authorised_budget()


def test_signed_rules_are_read_and_applied_literally() -> None:
    module = _module("build_treatment_adjudication_worksheet")
    signed = json.loads(SIGNED_PREREG.read_text(encoding="utf-8"))
    targets = signed["exit_rules"]["early_stop_before_human_adjudication"]["stage2_proxies"]
    clean = {name: 0 for name in targets}
    assert module.apply_signed_rules(clean)["passed"] is True
    # unbound_union 的已签规则是 baseline × 0.5，其余是 == 0
    failures = module.apply_signed_rules(
        {**clean, "unbound_union": targets["unbound_union"]["baseline"]}
    )
    assert failures["passed"] is False
    assert [item["proxy"] for item in failures["verdicts"] if not item["passed"]] == [
        "unbound_union"
    ]
    assert module.apply_signed_rules({**clean, "role_external_candidates": 1})["passed"] is False


def _candidate(index: int, claim: dict[str, object]) -> dict[str, object]:
    return {"candidate_id": f"c{index}", "role": "claims", "run": "r", "claim": claim, "fact": {}}


def test_stage2_uses_the_95_predicates() -> None:
    module = _module("build_treatment_adjudication_worksheet")
    base = {
        "subject": "600519.SH",
        "metric": "营业收入",
        "kind": "fact",
        "value_text": "1741 亿元",
        "unit_raw": "亿元",
        "unit": "元",
        "period_raw": "2026H1",
        "evidence_quote": "营收 1741 亿元",
        "reason_codes": [],
    }
    candidates = [
        _candidate(0, dict(base)),
        _candidate(1, {**base, "kind": "opinion"}),  # role-external
        _candidate(
            2,
            {
                **base,
                "period_raw": None,
                "period_end": None,
                "evidence_quote": "营收 1741 亿元（缺期间）",
            },
        ),  # field gap, no code
        _candidate(
            3,
            {
                **base,
                "reason_codes": ["period_not_in_packet"],
                "evidence_quote": "营收 1741 亿元（带码）",
            },
        ),  # code gap
        _candidate(
            4, {**base, "evidence_quote": "另一处 归母净利润 237.40 亿", "metric": "归母净利润"}
        ),
        _candidate(
            5, {**base, "evidence_quote": "另一处 归母净利润 237.40 亿", "metric": "归母净利润"}
        ),
    ]
    measured = module.stage2(candidates)
    assert measured["candidates_total"] == 6
    assert measured["in_role_candidates"] == 5
    assert measured["role_external_candidates"] == 1
    assert measured["unbound_fields_without_reason_code"] == 1, "缺字段且无码只算候选 2"
    assert measured["unbound_union"] == 2, "候选 2（字段级）与候选 3（码级）"
    assert measured["redundant_renderings"] == 1, "候选 4/5 同 subject+metric+quote+kind"


def test_worksheet_refuses_without_a_store(tmp_path: Path) -> None:
    module = _module("build_treatment_adjudication_worksheet")
    with pytest.raises(SystemExit, match="no store"):
        module.pool_of(tmp_path / "nope")


def test_landed_freeze_is_fail_closed_until_the_budget_line_is_filled() -> None:
    manifest = json.loads((FREEZE / "manifest.json").read_text(encoding="utf-8"))
    signed = json.loads(SIGNED_PREREG.read_text(encoding="utf-8"))
    reference = {
        item["name"]: item["attempt_ceiling"]
        for item in signed["budget_request"]["stage_1_live_run"]["historical_reference"][
            "per_execution"
        ]
    }
    assert manifest["status"] == "frozen_not_executed"
    assert manifest["runnable"] is False
    assert manifest["budget"]["per_run_ceilings"] == reference, "逐 run 上限必须逐字取自签认件"
    assert manifest["budget"]["total_attempt_ceiling"] == sum(reference.values())
    assert manifest["budget"]["authorised"] is (
        signed["budget_request"]["stage_1_live_run"]["requested_ceiling"] is not None
    ), "授权状态必须跟着签认件的 ceiling 走，不得自行认定"
    assert manifest["automatic_retries"] == 0 and manifest["gold_not_exposed_to_model"] is True
    assert manifest["profile"]["profile_sha256"]
    assert manifest["versions"]["lint"] == "claims-v2-lint-9"
    for entry in manifest["entries"]:
        assert len(entry["plan_file_sha256"]) == 64
        assert entry["scoped_units"] > 0
