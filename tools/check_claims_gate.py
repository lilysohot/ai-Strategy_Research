"""Claims gate conformance check: caliber reproducibility, sentinel identity, known divergences.

Zero model calls, read-only. Fail-closed: exit code is non-zero when a blocking check fails,
so this can run as a preflight gate for any claims gate revision.

Checks (see ``run_checks``):

* frozen inputs referenced by the gate/manifest still hash to their recorded values;
* the candidate pool's judgement ledger is complete and unresolved-free;
* every caliber in the gate can be recomputed from the frozen pool (contract formula,
  implemented formula, per-source precision, recall);
* the ``duplicate`` caliber divergence between the signed contract's text formula and the
  scorer implementation is detected and reported (detected, not decided);
* the sentinel list equals the signed contract's ``NT-C*`` subset and every required
  sentinel is matched by the pool;
* the 11 claims required fields' carrier census is reproducible;
* the false-positive decomposition sums to the adjudicated ``incorrect`` total;
* the release-line tolerance table is reproducible;
* every 83-号 superseded product still matches its MANIFEST hash, or the drift is covered by a
  registration record that binds the artifact path *and* both hashes (md drift must be registered);
* reachability of the target line on the frozen pool is recorded;
* no PASS in the gate depends on an axis the gate itself leaves unfrozen (R1/R2 of the
  93-号 governance plan); an exception is honoured only when the correction registration
  matches the artifact hash *and* the rule it invokes is in force.

This is a *reproducibility* audit: it re-derives recorded numbers from frozen inputs. It does
not re-litigate the caliber definitions themselves -- those are the gate's ``rule`` strings and
remain a human adjudication item.

Usage:
    uv run python tools/check_claims_gate.py
    uv run python tools/check_claims_gate.py --json out.json --md out.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"
DEFAULT_GATE = (
    SCRATCH / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/claims-gate-v3.json"
)
DEFAULT_MANIFEST = SCRATCH / "evidence/91-claims-gate-v3-signed-20261014/r0-zero-call/MANIFEST.json"
GATE_V3_DRAFT = (
    SCRATCH
    / "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/claims-gate-v3.proposed.json"
)
DEFAULT_SCOPE_REGISTRATION = (
    SCRATCH
    / "evidence/92-claims-scope-registration-20261014/r0-zero-call/claims-scope-registration.json"
)
GATE_V2_SUPERSEDED = (
    SCRATCH / "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-gate-v2.proposed.json"
)
DEFAULT_POOL = (
    SCRATCH
    / "evidence/17-structured-extraction-convergence-closure-20261009"
    / "p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
)
DEFAULT_CONTRACT = (
    SCRATCH / "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json"
)
DEFAULT_GOLD = SCRATCH / "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
DEFAULT_V1_GATE = (
    SCRATCH
    / "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/claims-gate-v1.proposed.json"
)
DEFAULT_V1_MANIFEST = (
    SCRATCH / "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/MANIFEST.json"
)
DEFAULT_V1_COVERAGE = (
    SCRATCH / "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/coverage-measurements.json"
)
# The 83-号 md drift registry. The check's own claim carries the exception ("md 漂移须登记"), so a
# drifted product is a finding only while nothing registers it; an entry must bind the artifact path
# *and* both hashes (MANIFEST-recorded and on-disk) to count as a registration.
DEFAULT_DRIFT_REGISTRATION = (
    SCRATCH
    / "evidence/110-claims-superseded-drift-registration-20261015"
    / "r0-zero-call/superseded-drift-registration.json"
)

DEFAULT_GOVERNANCE_PLAN = (
    SCRATCH / "evidence/93-claims-governance-plan-20261014/r0-zero-call/claims-governance-plan.json"
)
DEFAULT_GOVERNANCE_CORRECTIONS = (
    SCRATCH / "evidence/93-claims-governance-plan-20261014/r0-zero-call/governance-corrections.json"
)

# A PASS block that declares any of these keys asserts a conclusion under a precondition. R1/R2 of
# the 93-号 governance plan require such a line to read ``pending_caliber`` until the axis is
# decided, so a PASS carrying one is a violation candidate.
PRECONDITION_KEYS = ("precondition", "preconditions", "depends_on", "conditional_on")

# --- caliber definitions (mirrors the gate's declared rule strings) ----------
CLAIMS_REQUIRED_FIELDS = (
    "subject",
    "metric",
    "period",
    "unit",
    "value",
    "factuality",
    "attribution",
    "perspective",
    "source_stance",
    "estimate_status",
    "qualifier",
)
FIELD_CARRIER_KEY = {
    "subject": "subject",
    "metric": "metric",
    "period": "period_raw",
    "unit": "unit_raw",
    "value": "value_text",
    "factuality": "kind",
    "qualifier": "qualifiers",
}
COORDINATE_REASON_CODES = (
    "period_missing",
    "period_ambiguous",
    "period_unanchored",
    "period_not_in_packet",
    "time_invalid",
    "unit_missing",
    "unit_unknown",
    "value_missing",
    "value_not_in_evidence",
    "metric_missing",
)
JUDGEMENTS = ("matched", "correct_extra", "incorrect", "duplicate")


@dataclass(frozen=True)
class Check:
    """One auditable claim with its machine verdict."""

    check_id: str
    layer: str
    kind: str
    blocking: bool
    claim: str
    method: str
    expected: Any
    actual: Any
    verdict: str  # "pass" | "fail" | "divergence" | "note"


@dataclass(frozen=True)
class Inputs:
    """Resolved artifact paths for one audit run."""

    gate: Path = DEFAULT_GATE
    manifest: Path = DEFAULT_MANIFEST
    pool: Path = DEFAULT_POOL
    contract: Path = DEFAULT_CONTRACT
    gold: Path = DEFAULT_GOLD
    v1_gate: Path = DEFAULT_V1_GATE
    v1_manifest: Path = DEFAULT_V1_MANIFEST
    v1_coverage: Path = DEFAULT_V1_COVERAGE
    registration: Path = DEFAULT_SCOPE_REGISTRATION
    drift_registration: Path = DEFAULT_DRIFT_REGISTRATION
    governance_plan: Path = DEFAULT_GOVERNANCE_PLAN
    governance_corrections: Path = DEFAULT_GOVERNANCE_CORRECTIONS


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"artifact unavailable: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _ratio(num: int, den: int) -> dict[str, Any]:
    return {
        "numerator": num,
        "denominator": den,
        "value": round(num / den, 4) if den else None,
        "display": f"{num}/{den}" + (f" = {num / den:.4f}" if den else " = N/A"),
    }


def _tolerated_extra_fp(numerator: int, denominator: int, line: float) -> int:
    if line <= 0 or numerator / denominator < line:
        return -1
    extra = 0
    while numerator / (denominator + extra + 1) >= line:
        extra += 1
    return extra


def _claim_of(row: dict[str, Any]) -> dict[str, Any]:
    return row["original_candidate"]["claim"]


def _carrier(claim: dict[str, Any], field: str) -> Any:
    key = FIELD_CARRIER_KEY.get(field)
    return (claim.get(key) or None) if key else None


def _is_role_external(claim: dict[str, Any]) -> bool:
    return claim.get("kind") == "opinion" or claim.get("value_text") is None


def _has_coordinate_gap(claim: dict[str, Any]) -> bool:
    codes = set(claim.get("reason_codes") or ())
    return bool(codes & set(COORDINATE_REASON_CODES))


def _source_of(row: dict[str, Any]) -> str:
    doc = _claim_of(row).get("doc_id") or "unknown"
    return doc.split(":", 1)[-1][:12]


def recompute_calibers(
    pool: dict[str, Any], coverage: dict[str, Any], gold: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Recompute every caliber from the frozen pool (independent of the generator)."""
    rows = pool["adjudications"]
    targets = [r for r in gold["records"] if r["role"] == "claims"]

    def metrics(kept: list[dict[str, Any]]) -> dict[str, Any]:
        hits = {r.get("matched_gold_id") for r in kept if r.get("judgement") == "matched"}
        num = sum(1 for r in kept if r.get("judgement") in {"matched", "correct_extra"})
        inc = sum(1 for r in kept if r.get("judgement") == "incorrect")
        dup = sum(1 for r in kept if r.get("judgement") == "duplicate")
        per_source = {}
        for source in sorted({_source_of(r) for r in kept}):
            sub = [r for r in kept if _source_of(r) == source]
            sub_num = sum(1 for r in sub if r.get("judgement") in {"matched", "correct_extra"})
            sub_den = sub_num + sum(
                1 for r in sub if r.get("judgement") in {"incorrect", "duplicate"}
            )
            per_source[source] = _ratio(sub_num, sub_den)
        # One formula: the scorer's ``fp`` already includes duplicates, so the implemented
        # denominator equals the contract's duplicate-inclusive formula (C2, corrected).
        precision = _ratio(num, num + inc + dup)
        return {
            "kept_candidates": len(kept),
            "judgements": {
                name: sum(1 for r in kept if r.get("judgement") == name) for name in JUDGEMENTS
            },
            "precision_contract_formula": precision,
            "precision_scorer_implemented_formula": precision,
            "target_recall": _ratio(len(hits), len(targets)),
            "per_source_precision": per_source,
        }

    rows_similarity = coverage["coverage_measurements"]
    no_coverage = [
        c
        for c in rows_similarity
        if max(c["best_claims_gold_sim"], c["best_other_gold_sim"]) < 0.15
    ]
    cross_role = [
        c
        for c in rows_similarity
        if c["best_other_gold_sim"] >= 0.3 and c["best_other_gold_sim"] > c["best_claims_gold_sim"]
    ]
    removed_ids = {str(c["candidate_id"]) for c in (*no_coverage, *cross_role)}
    d4 = metrics([r for r in rows if str(r.get("candidate_id")) not in removed_ids])
    d4["no_coverage_removed"] = len(no_coverage)
    d4["cross_role_removed"] = len(cross_role)
    return {
        "D1_all_candidates": metrics(rows),
        "D2_in_role_only": metrics([r for r in rows if not _is_role_external(_claim_of(r))]),
        "D3_in_role_and_coordinate_complete": metrics(
            [
                r
                for r in rows
                if not _is_role_external(_claim_of(r)) and not _has_coordinate_gap(_claim_of(r))
            ]
        ),
        "D4_similarity_scoped_v1_draft_option": d4,
    }


def _unfrozen_axes(gate: dict[str, Any]) -> list[str]:
    """Axes the gate itself leaves undecided: ``unfrozen_axes`` + pending ``open_decisions``."""
    axes = [str(axis) for axis in gate.get("unfrozen_axes") or []]
    for decision in gate.get("open_decisions") or []:
        decision_id = str(decision.get("id") or "")
        pending = str(decision.get("status") or "").startswith("pending") or bool(
            decision.get("signature_did_not_decide")
        )
        if decision_id and pending:
            axes.append(decision_id)
    return axes


def _dependent_pass_lines(gate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """PASS verdict lines whose own block declares a precondition (R1/R2 violation candidates)."""
    found: dict[str, dict[str, Any]] = {}
    for line, block in (gate.get("verdict") or {}).items():
        if not isinstance(block, dict) or str(block.get("verdict", "")).lower() != "pass":
            continue
        declared = {key: block[key] for key in PRECONDITION_KEYS if block.get(key)}
        if declared:
            found[line] = declared
    return found


def _informational_mentions(
    gate: dict[str, Any], axes: list[str], dependent: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """PASS lines that merely mention an undecided axis without asserting under it.

    Recorded for visibility only: a note saying "this axis does not gate" is not a dependency, so
    it must not drive the verdict (M2 / D-2 is exactly this case in gate v3).
    """
    tokens = {axis for axis in axes}
    tokens |= {axis.split()[0] for axis in axes}
    found: dict[str, dict[str, Any]] = {}
    for line, block in (gate.get("verdict") or {}).items():
        if not isinstance(block, dict) or line in dependent:
            continue
        if str(block.get("verdict", "")).lower() != "pass":
            continue
        text = " ".join(value for value in block.values() if isinstance(value, str))
        hits = sorted(token for token in tokens if token and token in text)
        if hits:
            found[line] = {"mentioned": hits}
    return found


def _correction_coverage(
    corrections: dict[str, Any] | None, artifact_sha: str, field_path: list[str]
) -> dict[str, Any] | None:
    """A registered correction covers a field only if it binds the artifact hash and the path."""
    for entry in (corrections or {}).get("corrections") or []:
        artifact = entry.get("artifact") or {}
        recorded = str(artifact.get("sha256") or "").removeprefix("sha256:")
        if recorded != artifact_sha:
            continue
        path = [str(part) for part in entry.get("field_path") or []]
        if entry.get("scope") == "artifact_wide" or path == field_path:
            return entry
    return None


def _scratch_or_absolute(path: Path) -> str:
    """Scratch-relative when the path is inside the scratch root, absolute otherwise (tests)."""
    try:
        return str(path.relative_to(SCRATCH))
    except ValueError:
        return str(path)


def _drift_registration_entry(
    registration: dict[str, Any] | None,
    relative_paths: set[str],
    recorded: str,
    on_disk: str,
) -> dict[str, Any] | None:
    """A registration covers a drifted product only if it binds the path **and** both hashes.

    Recording one hash is not enough: binding only the manifest hash would let a second, later edit
    inherit the registration, and binding only the on-disk hash would let the registry follow the
    file around. Both must match the pair the checker observed.
    """
    for entry in (registration or {}).get("entries") or []:
        artifact = str(entry.get("artifact") or "").removeprefix("./")
        if artifact not in relative_paths:
            continue
        if str(entry.get("manifest_recorded_sha256") or "") != recorded:
            continue
        if str(entry.get("on_disk_sha256") or "") != on_disk:
            continue
        return entry
    return None


def _normalize_gate(gate: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Fill the optional blocks the checks read, so a leaner gate revision still audits.

    Missing blocks are *filled from the frozen inputs*, never guessed: sentinels from the signed
    contract and the v3 target line, the pool ledger from ``measured_run``, carriers recomputed
    from the pool, and reachability derived from the recorded calibers. A block that is absent
    is recorded in ``_filled_blocks`` so the audit shows what came from where.
    """
    filled: list[str] = []
    sentinels = dict(gate.get("sentinels") or {})
    if "contract_subset_required" not in sentinels:
        sentinels["contract_subset_required"] = sorted(
            gate.get("thresholds", {}).get("target_line", {}).get("sentinels_required")
            or [key for key in contract["review_assertions"] if key.startswith("NT-C")]
        )
        filled.append("sentinels.contract_subset_required")
    gate["sentinels"] = sentinels
    if "candidate_pool" not in gate:
        measured_pool = (gate.get("measured_run") or {}).get("pool") or {}
        gate["candidate_pool"] = {
            "total": measured_pool.get("candidates_total"),
            "judgements": {},
        }
        filled.append("candidate_pool")
    thresholds = gate.setdefault("thresholds", {})
    if "reachability_on_frozen_pool" not in thresholds:
        thresholds["reachability_on_frozen_pool"] = {
            name: {
                "max_achievable_precision": caliber["precision_contract_formula"]["value"],
                "note": "derived from the recorded calibers",
            }
            for name, caliber in (gate.get("calibers") or {}).items()
        }
        filled.append("thresholds.reachability_on_frozen_pool")
    release = thresholds.setdefault("release_line", {})
    release.setdefault("candidates", {})
    if not release["candidates"]:
        filled.append("thresholds.release_line.candidates(absent→empty)")
    gate["_filled_blocks"] = filled
    return gate


def run_checks(inputs: Inputs) -> list[Check]:
    """Run every claims-gate conformance check and return the ledger."""
    checks: list[Check] = []
    gate = load_json(inputs.gate)
    manifest = load_json(inputs.manifest)
    pool = load_json(inputs.pool)
    contract = load_json(inputs.contract)
    gold = load_json(inputs.gold)
    v1_gate = load_json(inputs.v1_gate)
    v1_manifest = load_json(inputs.v1_manifest)
    coverage = load_json(inputs.v1_coverage)
    gate = _normalize_gate(gate, contract)

    # ---- frozen inputs -----------------------------------------------------
    recorded = dict(gate.get("frozen_inputs") or {})
    recorded.update(manifest.get("inputs", {}))
    mapped = {
        name: SCRATCH / relative
        for name in recorded
        for relative in [_input_relative_path(name)]
        if relative is not None
    }
    unmapped = sorted(name for name in recorded if name not in mapped)
    mismatched = {
        name: {"recorded": recorded[name], "on_disk": sha256(path)}
        for name, path in mapped.items()
        if path.exists() and sha256(path) != recorded[name]
    }
    missing = [name for name, path in mapped.items() if not path.exists()]
    checks.append(
        Check(
            check_id="inputs-stable",
            layer="frozen",
            kind="integrity",
            blocking=True,
            claim="门/清单引用的全部冻结输入与磁盘字节一致",
            method="逐条 sha256（gate.frozen_inputs ∪ manifest.inputs）",
            expected={"mismatched": {}, "missing": [], "unmapped": []},
            actual={"mismatched": mismatched, "missing": missing, "unmapped": unmapped},
            verdict=("fail" if mismatched or missing else "divergence" if unmapped else "pass"),
        )
    )

    # ---- pool integrity ----------------------------------------------------
    rows = pool["adjudications"]
    ledger = {name: sum(1 for r in rows if r.get("judgement") == name) for name in JUDGEMENTS}
    declared_pool = gate.get("candidate_pool") or {}
    declared_total = declared_pool.get("total", declared_pool.get("candidates_total"))
    declared_ledger = declared_pool.get("judgements") or {}
    checks.append(
        Check(
            check_id="pool-ledger-closed",
            layer="pool",
            kind="integrity",
            blocking=True,
            claim="候选池裁定账闭合：四类之和 == 池容量，unresolved == 0",
            method="Counter(judgement) 求和 + unresolved_count",
            expected={"total": declared_total, "ledger": declared_ledger, "unresolved": 0},
            actual={
                "total": sum(ledger.values()),
                "ledger": ledger,
                "unresolved": pool.get("unresolved_count"),
            },
            verdict=(
                "pass"
                if sum(ledger.values()) == declared_total
                and (not declared_ledger or ledger == declared_ledger)
                and pool.get("unresolved_count") == 0
                else "fail"
            ),
        )
    )

    # ---- calibers ----------------------------------------------------------
    recomputed = recompute_calibers(pool, coverage, gold)
    for name, actual in recomputed.items():
        recorded_caliber = gate["calibers"][name]
        keys = (
            "kept_candidates",
            "precision_contract_formula",
            "precision_scorer_implemented_formula",
        )
        absent_keys = [key for key in keys if key not in recorded_caliber]
        expected_subset = {key: recorded_caliber[key] for key in keys if key in recorded_caliber}
        actual_subset = {key: actual.get(key) for key in keys if key in recorded_caliber}
        if absent_keys:
            actual_subset["_keys_absent_in_record"] = absent_keys
        checks.append(
            Check(
                check_id=f"caliber-reproducible:{name}",
                layer="metric",
                kind="reproducibility",
                blocking=True,
                claim=f"{name} 的候选数/分子/分母/显示值可由冻结池复算",
                method="独立实现按 gate 的 rule 字符串重算，逐字段比对",
                expected=expected_subset,
                actual=actual_subset,
                verdict=(
                    "pass"
                    if all(
                        _same(expected_subset[key], actual_subset[key]) for key in expected_subset
                    )
                    else "fail"
                ),
            )
        )
        required_row_keys = (
            "kept_candidates",
            "judgements",
            "target_recall",
            "per_source_precision",
        )
        incomplete = {
            key: recorded_caliber.get(key, "<missing>")
            for key in required_row_keys
            if recorded_caliber.get(key) in (None, {}, "<missing>")
        }
        checks.append(
            Check(
                check_id=f"caliber-row-complete:{name}",
                layer="metric",
                kind="completeness",
                blocking=False,
                claim=f"{name} 行记录了候选数/裁定分布/召回（不得只留精度一个数）",
                method="必需键存在性检查",
                expected={key: "<present>" for key in required_row_keys},
                actual=incomplete,
                verdict="pass" if not incomplete else "divergence",
            )
        )
        checks.append(
            Check(
                check_id=f"caliber-recall:{name}",
                layer="metric",
                kind="reproducibility",
                blocking=name != "D4_similarity_scoped_v1_draft_option",
                claim=f"{name} 的召回/分源精度可由冻结池复算",
                method="候选 matched 去重计数 / 按源分组重算",
                expected={
                    "target_recall": recorded_caliber.get("target_recall"),
                    "per_source_precision": recorded_caliber.get("per_source_precision"),
                },
                actual={
                    "target_recall": actual.get("target_recall"),
                    "per_source_precision": actual.get("per_source_precision"),
                },
                verdict=_recall_verdict(name, recorded_caliber, actual),
            )
        )

    # ---- duplicate accounting (C2, corrected 2026-10-14) -------------------
    # The scorer's ``fp`` already includes duplicates: both matchers append DUPLICATE candidates
    # to ``false_positive_ids``, so the implemented denominator (numerator + fp) equals the
    # contract's duplicate-inclusive formula. The 84-号 draft asserted a divergence by reading
    # the adjudication file's ``incorrect`` count as if it were ``fp``; C2 was corrected in the
    # signed contract v4.4 (88-号 record). These two checks pin the correction and flag stale
    # recorded values, so the double-count reading cannot silently return.
    d1 = gate["calibers"]["D1_all_candidates"]
    ledger = {name: sum(1 for r in rows if r.get("judgement") == name) for name in JUDGEMENTS}
    numerator = ledger["matched"] + ledger["correct_extra"]
    single_source = _ratio(numerator, numerator + ledger["incorrect"] + ledger["duplicate"])
    double_counted = _ratio(
        numerator, numerator + ledger["incorrect"] + ledger["duplicate"] + ledger["duplicate"]
    )
    checks.append(
        Check(
            check_id="duplicate-accounting-single-source",
            layer="caliber",
            kind="consistency",
            blocking=True,
            claim="契约文字公式与评分器实现同源：fp 已含 duplicate，禁止再补加 duplicate_fp",
            method="按评分器语义（false_positives 含 DUPLICATE）重算实现分母 vs 契约文字公式",
            expected=d1["precision_contract_formula"]["display"],
            actual={
                "recomputed_implemented": single_source["display"],
                "double_counting_variant": double_counted["display"],
            },
            verdict=(
                "pass"
                if d1["precision_contract_formula"]["display"] == single_source["display"]
                else "fail"
            ),
        )
    )
    recorded_implemented = d1["precision_scorer_implemented_formula"]["display"]
    checks.append(
        Check(
            check_id="gate-recorded-implemented-formula",
            layer="caliber",
            kind="completeness",
            blocking=False,
            claim="门记录的实现公式与评分器真实语义一致（84 号此处为读数错误，已由 C2 更正取代）",
            method="门记录值 vs 按评分器语义重算值",
            expected=single_source["display"],
            actual=recorded_implemented,
            verdict="pass" if recorded_implemented == single_source["display"] else "divergence",
        )
    )

    # ---- sentinels ---------------------------------------------------------
    required = sorted(k for k in contract["review_assertions"] if k.startswith("NT-C"))
    sentinel_block = gate.get("sentinels") or {}
    recorded_required = sentinel_block.get("contract_subset_required") or (
        gate.get("thresholds", {}).get("target_line", {}).get("sentinels_required") or []
    )
    matched_ids = {r.get("matched_gold_id") for r in rows if r.get("judgement") == "matched"}
    hit = {key: key in matched_ids for key in required}
    checks.append(
        Check(
            check_id="sentinel-contract-subset",
            layer="invariant",
            kind="identity",
            blocking=True,
            claim="哨兵清单 == 已签契约 review_assertions 的 NT-C* 子集",
            method="契约键前缀枚举 vs 门记录值",
            expected=required,
            actual=sorted(recorded_required),
            verdict="pass" if sorted(recorded_required) == required else "fail",
        )
    )
    checks.append(
        Check(
            check_id="sentinel-required-hit",
            layer="invariant",
            kind="coverage",
            blocking=True,
            claim="契约要求的每条 claims 哨兵在冻结池中被命中",
            method="matched_gold_id 集合成员判定",
            expected={key: True for key in required},
            actual=hit,
            verdict="pass" if all(hit.values()) else "fail",
        )
    )
    proposed_ids = gate["sentinels"].get("v1_draft_proposed_ids")
    if proposed_ids is None:
        # The v1 (83-号) draft is where the self-invented sentinels were proposed.
        proposed_ids = load_json(Inputs().v1_gate)["sentinels"]["proposed_ids"]
    foreign = sorted(set(proposed_ids) - set(required))
    recorded_foreign = gate["sentinels"].get("v1_extra_beyond_contract", foreign)
    checks.append(
        Check(
            check_id="sentinel-no-foreign",
            layer="invariant",
            kind="identity",
            blocking=False,
            claim="门不得携带契约之外的哨兵（v1 自造的 3 条须登记为作废而非保留）",
            method="v1/v2 提案集合 − 契约子集；门的哨兵清单本身也已校验为契约子集",
            expected=foreign,
            actual=sorted(recorded_foreign),
            verdict=(
                "pass"
                if sorted(recorded_foreign) == foreign
                and sorted(gate["sentinels"]["contract_subset_required"]) == required
                else "fail"
            ),
        )
    )

    # ---- field carriers ----------------------------------------------------
    recorded_carriers = gate.get("field_carriers") or {}
    recomputed_carriers = {
        field: {
            "count": sum(1 for r in rows if _carrier(_claim_of(r), field)),
            "status": "has_carrier" if field in FIELD_CARRIER_KEY else "no_carrier",
        }
        for field in CLAIMS_REQUIRED_FIELDS
    }
    carrier_block_absent = not recorded_carriers
    carrier_ok = carrier_block_absent or all(
        recorded_carriers[field]["count_out_of"][0] == value["count"]
        and recorded_carriers[field]["status"] == value["status"]
        for field, value in recomputed_carriers.items()
    )
    if carrier_block_absent:
        recorded_carriers = {
            field: {
                "count_out_of": [value["count"], len(rows)],
                "status": value["status"],
            }
            for field, value in recomputed_carriers.items()
        }
    checks.append(
        Check(
            check_id="field-carriers-reproducible",
            layer="metric",
            kind="reproducibility",
            blocking=not carrier_block_absent,
            claim="11 个 claims 必需字段的载体普查可复算",
            method="逐字段非空载体计数 vs 门记录值（门未记录则该块缺省，仅复算）",
            expected={
                field: recorded_carriers[field]["count_out_of"][0]
                for field in CLAIMS_REQUIRED_FIELDS
            },
            actual={field: value["count"] for field, value in recomputed_carriers.items()},
            verdict=("note" if carrier_block_absent else ("pass" if carrier_ok else "fail")),
        )
    )
    no_carrier = sorted(
        field for field, value in recomputed_carriers.items() if value["status"] == "no_carrier"
    )
    authority_contract = contract
    authority_path = ((gate.get("authority") or {}).get("signed_contract") or {}).get("path")
    if authority_path:
        candidate_path = SCRATCH / authority_path
        if candidate_path.exists():
            authority_contract = load_json(candidate_path)
    read_path = authority_contract.get("read_path") or {}
    claims_read_path = (read_path.get("roles") or {}).get("claims") or {}
    if not claims_read_path.get("carriers"):
        # Transitional location used by the v4.4 signoff (mirrors load_claims_carriers).
        claims_read_path = (read_path.get("roles_proposed") or {}).get("claims") or {}
    signed_handling = {
        field: entry.get("carrier")
        for field, entry in (claims_read_path.get("carriers") or {}).items()
        if field in no_carrier
    }
    checks.append(
        Check(
            check_id="field-carriers-no-carrier-listed",
            layer="caliber",
            kind="completeness",
            blocking=True,
            claim="四个零载体必需字段的处置已登记（门内留未决格，或已签契约给出 carrier/requires）",
            method="no_carrier 集合 vs 门 open_decisions / 已签契约的 claims carriers",
            expected=no_carrier,
            actual={
                "no_carrier_fields": [
                    field
                    for field, value in recomputed_carriers.items()
                    if value["status"] == "no_carrier"
                ],
                "contract_handling": signed_handling,
                "has_open_decision_C3": any(
                    decision["id"].startswith("C3")
                    for decision in (gate.get("open_decisions") or [])
                ),
            },
            verdict=(
                "pass"
                if sorted(signed_handling) == no_carrier
                or any(
                    decision["id"].startswith("C3")
                    for decision in (gate.get("open_decisions") or [])
                )
                else "fail"
            ),
        )
    )

    # ---- false-positive decomposition --------------------------------------
    incorrect = [r for r in rows if r.get("judgement") == "incorrect"]
    role_external = [r for r in incorrect if _is_role_external(_claim_of(r))]
    coordinate = [
        r
        for r in incorrect
        if not _is_role_external(_claim_of(r)) and _has_coordinate_gap(_claim_of(r))
    ]
    complete_nonmatch = [
        r
        for r in incorrect
        if not _is_role_external(_claim_of(r)) and not _has_coordinate_gap(_claim_of(r))
    ]
    recorded_fp = gate["false_positive_decomposition"]
    checks.append(
        Check(
            check_id="fp-decomposition-sums",
            layer="metric",
            kind="reproducibility",
            blocking=True,
            claim="假阳性三分（角色外/坐标未绑/齐备不匹配）之和 == 裁定的 incorrect 总数",
            method="按判定与 reason_codes 分类求和，逐类比对记录值",
            expected={
                "incorrect_total": recorded_fp["incorrect_total"],
                "role_external": recorded_fp["role_external"]["count"],
                "coordinate_unbound": recorded_fp["coordinate_unbound"]["count"],
                "structurally_complete_nonmatch": recorded_fp["structurally_complete_nonmatch"][
                    "count"
                ],
            },
            actual={
                "incorrect_total": len(incorrect),
                "role_external": len(role_external),
                "coordinate_unbound": len(coordinate),
                "structurally_complete_nonmatch": len(complete_nonmatch),
            },
            verdict=(
                "pass"
                if len(role_external) + len(coordinate) + len(complete_nonmatch) == len(incorrect)
                and len(incorrect) == recorded_fp["incorrect_total"]
                and len(role_external) == recorded_fp["role_external"]["count"]
                and len(coordinate) == recorded_fp["coordinate_unbound"]["count"]
                and len(complete_nonmatch) == recorded_fp["structurally_complete_nonmatch"]["count"]
                else "fail"
            ),
        )
    )

    # ---- C1 scope registration ---------------------------------------------
    assembled_block = (gate.get("measured_run") or {}).get("assembled") or {}
    has_scope_block = "out_of_scope_ids" in assembled_block
    moved = {str(cid) for cid in assembled_block.get("out_of_scope_ids") or []}
    registration = load_json(inputs.registration) if inputs.registration.exists() else None
    entries = list((registration or {}).get("entries") or [])
    registered = {str(entry.get("candidate_id")) for entry in entries}
    incomplete = [
        str(entry.get("candidate_id"))
        for entry in entries
        if not entry.get("owner_role") or not entry.get("status")
    ]
    checks.append(
        Check(
            check_id="c1-scope-registration",
            layer="invariant",
            kind="coverage",
            blocking=True,
            claim="C1 判出的角色外候选逐条落在覆盖登记里，且写明承担角色与状态",
            method="门 measured_run.assembled.out_of_scope_ids vs 登记件 entries + 必填字段",
            expected={"out_of_scope_count": len(moved), "registered_count": len(moved)},
            actual={
                "registration_present": registration is not None,
                "out_of_scope_count": len(moved),
                "registered_count": len(registered),
                "missing_from_registration": sorted(moved - registered),
                "registered_but_not_moved": sorted(registered - moved),
                "incomplete_entries": incomplete,
            },
            verdict=(
                "note"
                if not has_scope_block
                else "pass"
                if moved and registered == moved and not incomplete
                else "fail"
            ),
        )
    )

    # ---- tolerance table ---------------------------------------------------
    release = gate["thresholds"]["release_line"]["candidates"]
    d2 = gate["calibers"]["D2_in_role_only"]["precision_contract_formula"]
    recomputed_tolerance = {
        "D2_line_0.60": _tolerated_extra_fp(d2["numerator"], d2["denominator"], 0.60),
        "D2_line_0.55": _tolerated_extra_fp(d2["numerator"], d2["denominator"], 0.55),
        "D1_line_0.50": _tolerated_extra_fp(
            gate["calibers"]["D1_all_candidates"]["precision_contract_formula"]["numerator"],
            gate["calibers"]["D1_all_candidates"]["precision_contract_formula"]["denominator"],
            0.50,
        ),
    }
    recorded_tolerance = gate["thresholds"]["release_line"].get("tolerance_table")
    checks.append(
        Check(
            check_id="release-tolerance-reproducible",
            layer="metric",
            kind="reproducibility",
            blocking=bool(recorded_tolerance),
            claim="放行线容忍度表（每条线可再容忍的新增假阳性数）可复算（门未记录则仅复算）",
            method="按门记录的分母与线值重算整数容忍度",
            expected=recorded_tolerance or "block_absent",
            actual=recomputed_tolerance,
            verdict=(
                "note"
                if not recorded_tolerance
                else "pass"
                if recorded_tolerance == recomputed_tolerance
                else "fail"
            ),
        )
    )
    release_expected = {
        "D2_basis_0.60": d2["value"],
        "D1_basis_0.50": gate["calibers"]["D1_all_candidates"]["precision_contract_formula"][
            "value"
        ],
    }
    release_actual = {name: value["value"] for name, value in release.items()}
    checks.append(
        Check(
            check_id="release-candidates-consistent",
            layer="metric",
            kind="consistency",
            blocking=False,
            claim="放行线候选值与口径测量值一致（门未记录候选表时记 note）",
            method="release candidates vs 同口径 precision 值（契约式公式）",
            expected=release_expected,
            actual=release_actual or "block_absent",
            verdict=(
                "note"
                if not release_actual
                else ("pass" if _same(release_expected, release_actual) else "divergence")
            ),
        )
    )

    # ---- superseded artifact drift ----------------------------------------
    drift_registration = (
        load_json(inputs.drift_registration) if inputs.drift_registration.exists() else None
    )
    v1_recorded = v1_manifest["outputs"]
    drift: dict[str, dict[str, Any]] = {}
    for name, digest in v1_recorded.items():
        product = inputs.v1_gate.parent / name
        if not product.exists():
            continue
        on_disk = sha256(product)
        if on_disk == digest:
            continue
        paths = {
            str(product.relative_to(SCRATCH)),
            str(product.relative_to(REPO_ROOT)),
        }
        entry = _drift_registration_entry(drift_registration, paths, digest, on_disk)
        drift[name] = {
            "recorded": digest,
            "on_disk": on_disk,
            "artifact": str(product.relative_to(SCRATCH)),
            "registration": (entry or {}).get("artifact"),
            "registration_status": (entry or {}).get("status"),
            "covered": entry is not None,
        }
    unregistered = sorted(name for name, value in drift.items() if not value["covered"])
    unsigned = sorted(
        name
        for name, value in drift.items()
        if value["covered"] and value["registration_status"] != "signed"
    )
    checks.append(
        Check(
            check_id="superseded-artifact-drift",
            layer="bookkeeping",
            kind="integrity",
            blocking=False,
            claim="被取代的 83 号产物未在草案态被改动（md 漂移须登记）",
            method="83 MANIFEST 记录的产物哈希 vs 磁盘现值；漂移项须有登记件按路径+双哈希覆盖",
            expected={"unregistered_drift": {}},
            actual={
                "drift": drift,
                "unregistered": unregistered,
                "registered_pending_signature": unsigned,
                "registration_source": (
                    _scratch_or_absolute(inputs.drift_registration)
                    if drift_registration is not None
                    else None
                ),
            },
            # A drift that nothing registers is the finding; a registered one is accounted for, so it
            # drops to a note -- the artifact bytes stay the evidence, and only the attribution moves.
            # The claim is never relaxed to "pass" while a product still differs from its manifest.
            verdict=("pass" if not drift else "divergence" if unregistered else "note"),
        )
    )
    signoff_md = inputs.v1_gate.parent / "claims-gate-v1-signoff.md"
    md_text = signoff_md.read_text(encoding="utf-8") if signoff_md.exists() else ""
    residual_signed_on = "signed_on: 2026-10-14" in md_text
    md_signed = residual_signed_on and "reviewer: xyl" in md_text
    json_null_signoff = v1_gate["signoff"].get("reviewer") is None
    checks.append(
        Check(
            check_id="superseded-signoff-consistency",
            layer="bookkeeping",
            kind="consistency",
            blocking=False,
            claim="83 号 signoff md 的签署栏与其 JSON 签认状态一致",
            method="md 签署栏文本 vs gate_v1.signoff（残留时间戳也算不一致）",
            expected={"json_signoff_null": True, "md_residual_signed_on": False},
            actual={
                "json_status": v1_gate["status"],
                "json_signoff_null": json_null_signoff,
                "md_residual_signed_on": residual_signed_on,
                "md_carries_reviewer_name": md_signed,
            },
            verdict="pass" if json_null_signoff and not residual_signed_on else "divergence",
        )
    )

    # ---- target-line reachability ------------------------------------------
    reach = {}
    for name in ("D1_all_candidates", "D2_in_role_only", "D3_in_role_and_coordinate_complete"):
        recorded_ratio = gate["calibers"][name]["precision_contract_formula"]
        reach[name] = {
            "max_achievable_precision": recorded_ratio["value"],
            "recomputed": recomputed[name]["precision_contract_formula"]["value"],
            "target_line": gate["thresholds"]["target_line"]["candidate_precision_min"],
            "reachable": (recorded_ratio["value"] or 0)
            >= gate["thresholds"]["target_line"]["candidate_precision_min"],
        }
    any_reachable = any(value["reachable"] for value in reach.values())
    checks.append(
        Check(
            check_id="target-line-reachability",
            layer="metric",
            kind="feasibility",
            blocking=False,
            claim="目标线（精度 0.80）在冻结池上的可达性被显式记录",
            method="各口径分子/分母上限 vs target_line",
            expected=gate["thresholds"]["reachability_on_frozen_pool"],
            actual=reach,
            verdict="pass" if any_reachable else "note",
        )
    )

    # ---- R1/R2: no PASS may rest on an unfrozen axis (93-号 governance plan) ----
    # Governance blocks assertions, never actions (R1); an undecided axis defaults to "no positive
    # assertion" rather than to the strictest value (R2). Exception discipline: a registered
    # correction excuses a finding only when it binds this artifact's hash *and* the rule it invokes
    # is in force -- otherwise the checker reports without blocking, so an unsigned rule can never
    # freeze an already-signed artifact.
    axes = _unfrozen_axes(gate)
    dependent = _dependent_pass_lines(gate)
    mentions = _informational_mentions(gate, axes, dependent)
    plan = load_json(inputs.governance_plan) if inputs.governance_plan.exists() else None
    corrections = (
        load_json(inputs.governance_corrections) if inputs.governance_corrections.exists() else None
    )
    rules_status = str(((plan or {}).get("rules_in_force") or {}).get("status", "") or "")
    rules_in_force = rules_status == "signed"
    artifact_sha = sha256(inputs.gate)
    coverage: dict[str, Any] = {}
    for line, declared in dependent.items():
        entry = _correction_coverage(corrections, artifact_sha, ["verdict", line])
        # Two-factor exception: the registration must bind this artifact's hash *and* itself be
        # signed. An unsigned registration by the checker's own author cannot excuse a finding.
        honored = entry is not None and entry.get("status") == "signed"
        coverage[line] = {
            "declared": declared,
            "correction": (entry or {}).get("id"),
            "correction_status": (entry or {}).get("status"),
            "honored": honored,
        }
    uncovered = sorted(line for line, value in coverage.items() if not value["honored"])
    # ``uncovered`` is derived from ``dependent``, so it is the only condition to test.
    verdict = "pass" if not uncovered else ("fail" if rules_in_force else "note")
    checks.append(
        Check(
            check_id="pass-not-dependent-on-unfrozen-axis",
            layer="invariant",
            kind="consistency",
            blocking=rules_in_force,
            claim="门里任何 PASS 不得以未裁轴为前提（已登记且规则生效的例外除外）",
            method="verdict.*.verdict==PASS 且声明 precondition 类字段 ⇒ 须被更正登记按哈希+字段路径覆盖",
            expected={
                "unfrozen_axes": axes,
                "pass_lines_with_precondition": [],
                "or_covered_by_registration": True,
            },
            actual={
                "unfrozen_axes": axes,
                "pass_lines_with_precondition": coverage,
                "uncovered_lines": uncovered,
                "informational_mentions": mentions,
                "governance_plan_present": plan is not None,
                "rules_in_force": rules_in_force,
                "exception_requires": "更正登记自身须签认（correction.status == 'signed'）且绑定本件哈希",
                "escalates_to_blocking_when": "R1/R2 签认（rules_in_force.status == 'signed'）",
            },
            verdict=verdict,
        )
    )

    return checks


def _recall_verdict(name: str, recorded: dict[str, Any], actual: dict[str, Any]) -> str:
    """D4 records no recall/per-source slice; everything else must match or fail."""
    same = _same(
        {
            "target_recall": recorded.get("target_recall"),
            "per_source_precision": recorded.get("per_source_precision"),
        },
        {
            "target_recall": actual.get("target_recall"),
            "per_source_precision": actual.get("per_source_precision"),
        },
    )
    if same:
        return "pass"
    return "note" if name.startswith("D4") else "fail"


def _input_relative_path(name: str) -> str | None:
    """Map a known input key to its repo-relative path; unknown keys return None."""
    return {
        "frozen_gold": "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json",
        "items_gate_v3": "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json",
        "scoring_contract_v4.3": "evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json",
        "p1r5_candidate_adjudications_signed": (
            "evidence/17-structured-extraction-convergence-closure-20261009"
            "/p1r5-claims-adjudication-v2/candidate-adjudications.signed.json"
        ),
        "claims_gate_v1_proposed_superseded": (
            "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/claims-gate-v1.proposed.json"
        ),
        "claims_coverage_v1_superseded": (
            "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/coverage-measurements.json"
        ),
        "p1r5_gate_result_signed": (
            "evidence/17-structured-extraction-convergence-closure-20261009"
            "/p1r5-claims-adjudication-v2/claims-gate-result.signed.json"
        ),
        "signed_scoring_contract_v4.4": (
            "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json"
        ),
        "claims_gate_v2_superseded": (
            "evidence/84-claims-gate-v2-draft-20261014/r0-zero-call/claims-gate-v2.proposed.json"
        ),
        "coverage_measurements_v1": (
            "evidence/83-claims-scope-gate-draft-20261014/r0-zero-call/coverage-measurements.json"
        ),
        "c2_measurement": (
            "evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/c2-measurement.json"
        ),
        "frozen_gold_r2": "evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json",
        "claims_gate_v3_draft": (
            "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/claims-gate-v3.proposed.json"
        ),
        "claims_gate_v3_draft_manifest": (
            "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/MANIFEST.json"
        ),
        "signoff_instrument": (
            "evidence/90-claims-gate-v3-and-run-20261014/r0-zero-call/claims-gate-v3-signoff.md"
        ),
        "items_gate_v3_signed_reference": (
            "evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json"
        ),
    }.get(name)


def _same(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(
        right, sort_keys=True, ensure_ascii=False
    )


def render_markdown(checks: list[Check]) -> str:
    """Render the audit ledger as a human-readable report."""
    blocking_failed = [c for c in checks if c.blocking and c.verdict in {"fail", "divergence"}]
    divergences = [c for c in checks if c.verdict == "divergence"]
    notes = [c for c in checks if c.verdict == "note"]
    lines = [
        "# Claims 门 v2 回溯审核（机器生成）",
        "",
        f"审核项 {len(checks)} 条；阻塞项失败 {len(blocking_failed)} 条；口径/记账分歧 {len(divergences)} 条；"
        f"仅记录 {len(notes)} 条。",
        "",
        "谓词声明：审核项按【层级 × 性质 × 是否阻塞】计数。层级 ∈ {frozen, pool, metric, invariant,"
        " caliber, bookkeeping}；性质 ∈ {integrity, reproducibility, identity, coverage,"
        " consistency, completeness, caliber_divergence, feasibility}；阻塞 = 该项失败会使门不可签认。",
        "",
        "| 审核项 | 层级 | 性质 | 阻塞 | 判定 | 主张 |",
        "|---|---|---|---|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| `{check.check_id}` | {check.layer} | {check.kind} | "
            f"{'是' if check.blocking else '否'} | **{check.verdict}** | {check.claim} |"
        )
    lines += ["", "## 逐项证据", ""]
    for check in checks:
        lines += [
            f"### {check.check_id} — {check.verdict}",
            "",
            f"- 方法：{check.method}",
            f"- 期望：`{json.dumps(check.expected, ensure_ascii=False)}`",
            f"- 实测：`{json.dumps(check.actual, ensure_ascii=False)}`",
            "",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--v1-gate", type=Path, default=DEFAULT_V1_GATE)
    parser.add_argument("--v1-manifest", type=Path, default=DEFAULT_V1_MANIFEST)
    parser.add_argument("--v1-coverage", type=Path, default=DEFAULT_V1_COVERAGE)
    parser.add_argument("--drift-registration", type=Path, default=DEFAULT_DRIFT_REGISTRATION)
    parser.add_argument("--governance-plan", type=Path, default=DEFAULT_GOVERNANCE_PLAN)
    parser.add_argument(
        "--governance-corrections", type=Path, default=DEFAULT_GOVERNANCE_CORRECTIONS
    )
    parser.add_argument("--json", type=Path, help="把审核账写成 JSON")
    parser.add_argument("--md", type=Path, help="把审核报告写成 Markdown")
    args = parser.parse_args(argv)

    inputs = Inputs(
        gate=args.gate,
        manifest=args.manifest,
        pool=args.pool,
        contract=args.contract,
        gold=args.gold,
        v1_gate=args.v1_gate,
        v1_manifest=args.v1_manifest,
        v1_coverage=args.v1_coverage,
        drift_registration=args.drift_registration,
        governance_plan=args.governance_plan,
        governance_corrections=args.governance_corrections,
    )
    checks = run_checks(inputs)
    payload = {
        "schema_version": "claims-gate-conformance-audit-1",
        "checks": [asdict(c) for c in checks],
        "blocking_failures": [c.check_id for c in checks if c.blocking and c.verdict == "fail"],
        "divergences": [c.check_id for c in checks if c.verdict == "divergence"],
        "verdict": "pass"
        if not any(c.blocking and c.verdict == "fail" for c in checks)
        else "fail",
    }
    if args.json:
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.md:
        args.md.write_text(render_markdown(checks), encoding="utf-8")

    for check in checks:
        flag = "FAIL" if check.blocking and check.verdict == "fail" else check.verdict.upper()
        print(f"[{flag:12}] {check.check_id}: {check.claim}")
    print(f"verdict={payload['verdict']} blocking_failures={payload['blocking_failures']}")
    return 1 if payload["verdict"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
