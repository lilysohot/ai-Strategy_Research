"""Development-only exclusion experiment: archived item rescore, never new model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import p0_baseline

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = HERE / "material-semantics-runs"
SCOPE = HERE / "r2-nonminutes-scope-v1.json"
V13_REPORT = RUNS / "report-46caccfc1c7d23ef3858a8a501560c07b250888b0b3f189fdff75d8ba6bc6b4b.json"
V13_SCORE = RUNS / "item-contract-score-v2-203a306ebfc2dc881fbbffc78a76b08d771a5b5c596c4cde87c3adadd40a04f0.json"
PINS = {
    V13_REPORT: "34cc841e98257580889681907f86cce54003f4a46e5df8f14df451fbd502f8ab",
    V13_SCORE: "ffcedfe0c35bfbcd1c2035f87ed26a820425aac5865e892e7ef70637a1ccfd76",
    HERE / "verify_material_item_contract_v2.py": "442ff9c69d3266ba137cc662befe13d7041e1e7ceb5fdf55277107939fe361a6",
    HERE / "r2-item-acceptance-policy-v2.json": "c0fed47f53ddc6b7966a32a30054e4a87c28914234077a0dc2b5122775473852",
    ROOT / "data/corpus/.audit/r2_material_micro_gold_v1_20260913.json": "214b1f49f82e36c7c2b59496ada20228730439d0bc4b6f17fc51ff87122077c5",
    ROOT / "data/corpus/.audit/r1_material_gold_v1_20260913.json": "e8b541a6557189898bd8b86beab66af4b294cec19bc89c7d81e069f70ff0ac1b",
    HERE / "r2-p4-item-plan.json": "96ca9d113dab13a18e22a2f726ec2df04bdb9b747636d0183e6852cc25a1bc7e",
    HERE / "r2-p3i-inventory.json": "b2632e12ad5421721538587a159fdac2f5b8f08007e21c6c196e9ac1c33e483d",
    HERE / "p4_item_trial.py": "035af033498e59151509e4b771debdcd5214b046407f2689e67fb59a800911cc",
    HERE / "p4-runs/p4-items-1/audit-export.json": "0bcd1497e74195b6c44ec487794266fdd0749ebeb1547ee59ad093d63c883966",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate() -> dict[str, Any]:
    network = p0_baseline.block_external()
    for path, expected in PINS.items():
        if sha(path) != expected:
            raise ValueError(f"input_drift:{path.name}")
    import p4_item_trial as p4
    import verify_material_item_contract_v2 as legacy

    scope = read(SCOPE)
    included = set(scope["included_sample_ids"])
    excluded = set(scope["excluded_sample_ids"])
    assert len(included) == 3 and not included & excluded
    source_samples = {row["sample_id"]: row for row in read(legacy.SOURCE_GOLD)["samples"]}
    for sample_id in included:
        sample = source_samples[sample_id]
        assert sample["split"] == "development"
        assert sample["material_type"] not in scope["excluded_material_types"]
    source_paths = {(ROOT / source_samples[s]["source_path"]).resolve() for s in included}
    source_opens: set[str] = set()
    all_corpus_files = (ROOT / "data/corpus").resolve()

    def corpus_read_guard(event: str, args: tuple[object, ...]) -> None:
        if event != "open" or not args or not isinstance(args[0], (str, bytes)):
            return
        filename = args[0].decode() if isinstance(args[0], bytes) else args[0]
        path = Path(filename).resolve()
        if path.is_relative_to(all_corpus_files) and path.suffix.lower() in {".pdf", ".docx", ".md"}:
            if path not in source_paths:
                raise PermissionError("excluded_or_holdout_source_read")
            source_opens.add(str(path.relative_to(ROOT)))

    sys.addaudithook(corpus_read_guard)
    micro = read(legacy.DEFAULT_MICRO_GOLD)
    retained_scopes = [s for s in micro["scopes"] if s["sample_id"] in included]
    assert {s["scope_id"] for s in retained_scopes} == set(scope["included_scope_ids"])
    assert sum(len(s["items"]) for s in retained_scopes) == scope["historical_v13_item_count"]
    for s in retained_scopes:
        if sha(ROOT / s["source_path"]) != s["source_sha256"]:
            raise ValueError("source_revision_drift")
    historical = legacy.score_report(
        V13_REPORT, legacy.DEFAULT_POLICY, read(legacy.DEFAULT_POLICY),
        {**micro, "scopes": retained_scopes},
    )
    archived = read(V13_SCORE)
    # Confirm the new subset replay exactly reproduces the archived per-scope facts.
    expected_scopes = [s for s in archived["scopes"] if s["scope_id"] in scope["included_scope_ids"]]
    assert historical["scopes"] == expected_scopes
    historical["note"] = "Subset rescore, not a new extraction and not a replacement for v13."
    per_scope = []
    for row in historical["scopes"]:
        semantic_correct = sum(d["field_checks"]["semantic_type"] for d in row["detail"])
        compared = len(row["detail"])
        semantic_accuracy = semantic_correct / compared if compared else None
        reasons = []
        if row["matched_items"] != row["gold_items"]:
            reasons.append("item_recall_below_1")
        if row["matched_items"] != row["predicted_items"]:
            reasons.append("item_precision_below_1")
        if semantic_accuracy is None or semantic_accuracy < historical["thresholds"]["semantic_accuracy"]:
            reasons.append("per_scope_semantic_accuracy_below_0.9")
        critical = [e for e in historical["critical_error_detail"] if e["scope_id"] == row["scope_id"]]
        if critical:
            reasons.append("critical_error")
        per_scope.append({
            "scope_id": row["scope_id"], "gold_items": row["gold_items"],
            "predicted_items": row["predicted_items"], "matched_items": row["matched_items"],
            "semantic_correct": semantic_correct, "semantic_compared": compared,
            "semantic_accuracy": semantic_accuracy, "unmatched_gold": row["unmatched_gold"],
            "semantic_mismatch_ids": [d["gold_item"] for d in row["detail"] if not d["field_checks"]["semantic_type"]],
            "subset_diagnostic_status": "failed" if reasons else "passed_historical_item_subset_only",
            "reasons": reasons,
        })

    saved = read(HERE / "r2-p4-item-plan.json")
    # Preserve the original plan identity for parsing archived wires; never generate a new run.
    plan = p4.TrialPlan(**{
        **saved,
        "obligations": tuple(p4.Obligation(**o) for o in saved["obligations"]),
        "scope_ids": tuple(saved["scope_ids"]), "empty_scope_ids": tuple(saved["empty_scope_ids"]),
        "unknown_field_vocabulary": tuple(saved["unknown_field_vocabulary"]),
    })
    retained = [o for o in plan.obligations if o.sample_id in included]
    assert len(retained) == scope["current_p3i_p4_item_count"]
    audit = read(HERE / "p4-runs/p4-items-1/audit-export.json")
    assert len(audit["attempts"]) == 1
    attempt = audit["attempts"][0]
    assert sha_bytes(attempt["raw"]) == attempt["raw_sha"]
    assert sha_bytes(attempt["request"]) == attempt["request_sha"]
    request = json.loads(attempt["request"].split("INPUT_JSON=", 1)[1])
    attempted_ids = {o["obligation_id"] for o in request["obligations"]}
    by_id = {o.obligation_id: o for o in plan.obligations}
    assert all(by_id[i].sample_id in included for i in attempted_ids)
    parsed, _ = p4._parse_records(plan, (attempt["raw"],), attempted_ids)
    p4_rows = []
    for sample_id in scope["included_sample_ids"]:
        members = {o.obligation_id for o in retained if o.sample_id == sample_id}
        attempted = members & attempted_ids
        valid = members & parsed.keys()
        p4_rows.append({
            "sample_id": sample_id, "obligations": len(members), "attempted": len(attempted),
            "protocol_valid": len(valid), "protocol_invalid": len(attempted - valid),
            "not_attempted": len(members - attempted_ids),
            "status": "not_evaluated" if not attempted else "failed_protocol",
        })

    inputs = {str(p.relative_to(ROOT)): sha(p) for p in (*PINS, SCOPE, Path(__file__))}
    report = read(V13_REPORT)
    for row in report["samples"]:
        if row["sample_id"] in included:
            path = RUNS / f"{row['material_run_id']}.json"
            inputs[str(path.relative_to(ROOT))] = sha(path)
    return {
        "version": "r2-nonminutes-diagnostic-1", "split": "development",
        "new_model_calls": 0, "postgres_access": 0, "network": network,
        "included_sample_ids": scope["included_sample_ids"],
        "excluded_sample_ids": scope["excluded_sample_ids"],
        "source_paths_opened": sorted(source_opens),
        "excluded_source_reads": 0, "holdout_source_reads": 0,
        "v13_historical_before": {"metrics": archived["metrics"], "counts": archived["counts"]},
        "v13_nonminutes_rescore": historical,
        "v13_nonminutes_per_scope": per_scope,
        "v13_independent_critical_error_veto": bool(historical["critical_error_detail"]),
        "p4_current_nonminutes": {
            "obligations": len(retained), "attempted": len(attempted_ids),
            "protocol_valid": len(parsed), "protocol_invalid": len(attempted_ids - parsed.keys()),
            "not_attempted": len(retained) - len(attempted_ids), "samples": p4_rows,
            "status": "failed_protocol_and_incomplete_evaluation",
            "semantic_acceptance": "not_certified_known_scorer_and_contract_gaps",
        },
        "relations": "not_evaluated", "holdout": "not_evaluated", "r2_cli": "not_evaluated",
        "conclusion": "Removing minute samples does not make the retained R2 scope pass.",
        "input_sha256": inputs,
    }


def sha_bytes(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = evaluate()
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps({
        "v13_metrics": result["v13_nonminutes_rescore"]["metrics"],
        "v13_counts": result["v13_nonminutes_rescore"]["counts"],
        "v13_per_scope": result["v13_nonminutes_per_scope"],
        "p4": result["p4_current_nonminutes"], "conclusion": result["conclusion"],
        "new_model_calls": 0,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
