"""Claims gate conformance invariants (84/85 号草案 + tools/check_claims_gate.py).

These tests pin the properties the claims gate must satisfy before it can be signed:
sentinel identity with the signed contract, caliber reproducibility from the frozen pool,
detection of the duplicate-formula divergence, and fail-closed behaviour on missing or
mutated artifacts.

They read the real frozen artifacts under ``.scratch/claims-r2-role-isolation`` (same
convention as ``tests/test_corpus_contract_gate.py``), so they are integration tests: if a
frozen input is renamed the module-level paths must be updated in the same change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.check_claims_gate import (
    CLAIMS_REQUIRED_FIELDS,
    Inputs,
    load_json,
    main,
    recompute_calibers,
    run_checks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"
# The superseded v2 draft is audited explicitly by one test: it carries the two known defects
# (stale implemented formula, incomplete D4 row) that the current gate v3 no longer has.
GATE_V2 = (
    SCRATCH / "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-gate-v2.proposed.json"
)
GATE_V2_MANIFEST = SCRATCH / "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/MANIFEST.json"


@pytest.fixture(scope="module")
def checks() -> list:
    return run_checks(Inputs())


def _by_id(checks: list, check_id: str):
    matches = [c for c in checks if c.check_id == check_id]
    assert matches, f"check {check_id} missing"
    return matches[0]


def _mutated_gate(tmp_path: Path, mutate) -> Path:
    gate = load_json(Inputs().gate)
    mutate(gate)
    target = tmp_path / "claims-gate-mutated.json"
    target.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


# ------------------------------------------------------------------ real artifacts


def test_real_artifacts_pass_every_blocking_check(checks: list) -> None:
    failures = [c.check_id for c in checks if c.blocking and c.verdict == "fail"]
    assert failures == []


def test_sentinel_set_equals_signed_contract_subset(checks: list) -> None:
    check = _by_id(checks, "sentinel-contract-subset")
    assert check.verdict == "pass"
    assert check.expected == ["NT-C11", "NT-C12", "NT-C13"]
    hit = _by_id(checks, "sentinel-required-hit")
    assert hit.verdict == "pass"
    assert all(hit.actual.values())


def test_v1_self_invented_sentinels_are_registered_not_kept(checks: list) -> None:
    check = _by_id(checks, "sentinel-no-foreign")
    assert check.verdict == "pass"
    assert sorted(check.actual) == ["NT-C01", "NT-C03", "NT-C08"]


def test_calibers_reproduce_from_the_frozen_pool(checks: list) -> None:
    for name in (
        "D1_all_candidates",
        "D2_in_role_only",
        "D3_in_role_and_coordinate_complete",
        "D4_similarity_scoped_v1_draft_option",
    ):
        assert _by_id(checks, f"caliber-reproducible:{name}").verdict == "pass"
    for name in ("D1_all_candidates", "D2_in_role_only", "D3_in_role_and_coordinate_complete"):
        assert _by_id(checks, f"caliber-recall:{name}").verdict == "pass"


def test_target_line_is_recorded_as_unreachable_on_the_frozen_pool(checks: list) -> None:
    check = _by_id(checks, "target-line-reachability")
    d2 = check.actual["D2_in_role_only"]
    assert d2["reachable"] is False
    assert d2["max_achievable_precision"] == pytest.approx(0.6296, abs=1e-4)
    assert d2["target_line"] == 0.8


def test_duplicate_accounting_is_single_source(checks: list) -> None:
    """C2 correction (2026-10-14): the formulas agree; adding duplicate_fp would double count."""
    check = _by_id(checks, "duplicate-accounting-single-source")
    assert check.verdict == "pass"
    assert check.expected == "56/110 = 0.5091"
    assert check.actual["recomputed_implemented"] == "56/110 = 0.5091"
    assert check.actual["double_counting_variant"] == "56/113 = 0.4956"
    pool = load_json(Inputs().pool)
    duplicates = sum(1 for row in pool["adjudications"] if row.get("judgement") == "duplicate")
    incorrect = sum(1 for row in pool["adjudications"] if row.get("judgement") == "incorrect")
    # The scorer's fp counts duplicates as well, which is exactly why 56/107 was a misreading.
    assert duplicates == 3
    assert incorrect + duplicates == 54


def test_superseded_v2_draft_is_flagged_on_both_known_defects() -> None:
    """The 84-号 draft still records 56/107 and an incomplete D4 row; auditing it must say so."""
    checks = run_checks(Inputs(gate=GATE_V2, manifest=GATE_V2_MANIFEST))
    stale = _by_id(checks, "gate-recorded-implemented-formula")
    assert stale.verdict == "divergence"
    assert stale.expected == "56/110 = 0.5091"
    assert stale.actual == "56/107 = 0.5234"
    incomplete = [
        check.check_id
        for check in checks
        if check.check_id.startswith("caliber-row-complete:") and check.verdict != "pass"
    ]
    assert incomplete == ["caliber-row-complete:D4_similarity_scoped_v1_draft_option"]


def test_false_positive_decomposition_sums_to_the_adjudicated_total(checks: list) -> None:
    check = _by_id(checks, "fp-decomposition-sums")
    assert check.verdict == "pass"
    actual = check.actual
    assert (
        actual["role_external"]
        + actual["coordinate_unbound"]
        + actual["structurally_complete_nonmatch"]
        == actual["incorrect_total"]
        == 51
    )


def test_carrier_census_has_exactly_four_uncarried_fields(checks: list) -> None:
    check = _by_id(checks, "field-carriers-reproducible")
    # gate v3 does not carry a carrier block, so this is a recompute-only note.
    assert check.verdict == "note"
    uncarried = [
        field for field, count in check.actual.items() if count == 0 and field in check.actual
    ]
    recorded = _by_id(checks, "field-carriers-no-carrier-listed")
    assert sorted(recorded.expected) == sorted(uncarried)
    assert sorted(uncarried) == [
        "attribution",
        "estimate_status",
        "perspective",
        "source_stance",
    ]
    assert len(CLAIMS_REQUIRED_FIELDS) == 11


def test_c1_scope_registration_covers_every_moved_out_candidate(checks: list) -> None:
    """C1 moves role-external candidates out of claims; each must be registered for coverage."""
    check = _by_id(checks, "c1-scope-registration")
    assert check.verdict == "pass"
    assert check.actual["registration_present"] is True
    assert check.actual["out_of_scope_count"] == check.actual["registered_count"] == 29
    assert check.actual["missing_from_registration"] == []
    assert check.actual["registered_but_not_moved"] == []
    assert check.actual["incomplete_entries"] == []


def test_c1_registration_dropping_an_entry_fails_closed(tmp_path: Path) -> None:
    registration = load_json(Inputs().registration)
    registration["entries"] = registration["entries"][:-1]
    trimmed = tmp_path / "claims-scope-registration.json"
    trimmed.write_text(json.dumps(registration, ensure_ascii=False), encoding="utf-8")
    checks = run_checks(Inputs(registration=trimmed))
    check = _by_id(checks, "c1-scope-registration")
    assert check.verdict == "fail"
    assert check.actual["missing_from_registration"]


def test_c1_registration_entry_missing_owner_fails_closed(tmp_path: Path) -> None:
    registration = load_json(Inputs().registration)
    registration["entries"][0]["owner_role"] = ""
    broken = tmp_path / "claims-scope-registration-broken.json"
    broken.write_text(json.dumps(registration, ensure_ascii=False), encoding="utf-8")
    checks = run_checks(Inputs(registration=broken))
    assert _by_id(checks, "c1-scope-registration").verdict == "fail"


def test_every_caliber_row_is_complete_or_flagged(checks: list) -> None:
    """Gate v3 rows are all complete (the 84-号 incomplete D4 row is covered by its own test)."""
    incomplete = [
        c.check_id
        for c in checks
        if c.check_id.startswith("caliber-row-complete:") and c.verdict != "pass"
    ]
    assert incomplete == []


def test_recompute_is_caliber_definition_driven() -> None:
    """复算只用冻结池 + 定义，不读取门里记录的数值。"""
    pool = load_json(Inputs().pool)
    coverage = load_json(Inputs().v1_coverage)
    gold = load_json(Inputs().gold)
    recomputed = recompute_calibers(pool, coverage, gold)
    assert recomputed["D1_all_candidates"]["precision_contract_formula"]["numerator"] == 56
    assert recomputed["D2_in_role_only"]["kept_candidates"] == 81
    assert recomputed["D2_in_role_only"]["target_recall"]["display"] == "20/20 = 1.0000"
    assert recomputed["D4_similarity_scoped_v1_draft_option"]["kept_candidates"] == 65


# ------------------------------------------------------------------ mutations


def test_foreign_sentinel_in_the_gate_fails_closed(tmp_path: Path) -> None:
    def mutate(gate: dict) -> None:
        # gate v3 declares its sentinels on the target line; add a contract-foreign one.
        gate["thresholds"]["target_line"]["sentinels_required"] = [
            "NT-C01",
            "NT-C11",
            "NT-C12",
            "NT-C13",
        ]

    inputs = Inputs(gate=_mutated_gate(tmp_path, mutate))
    checks = run_checks(inputs)
    assert _by_id(checks, "sentinel-contract-subset").verdict == "fail"
    assert "sentinel-contract-subset" in [
        c.check_id for c in checks if c.blocking and c.verdict == "fail"
    ]
    assert main(["--gate", str(inputs.gate)]) == 1


def test_recorded_caliber_that_contradicts_the_pool_fails_closed(tmp_path: Path) -> None:
    def mutate(gate: dict) -> None:
        gate["calibers"]["D2_in_role_only"]["precision_contract_formula"]["numerator"] = 52

    inputs = Inputs(gate=_mutated_gate(tmp_path, mutate))
    checks = run_checks(inputs)
    assert _by_id(checks, "caliber-reproducible:D2_in_role_only").verdict == "fail"
    assert main(["--gate", str(inputs.gate)]) == 1


def test_missing_artifact_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="artifact unavailable"):
        run_checks(Inputs(gate=tmp_path / "missing.json"))


def test_frozen_inputs_are_stable_against_the_scratch_root(checks: list) -> None:
    check = _by_id(checks, "inputs-stable")
    assert check.verdict == "pass"
    assert check.actual == {"mismatched": {}, "missing": [], "unmapped": []}
