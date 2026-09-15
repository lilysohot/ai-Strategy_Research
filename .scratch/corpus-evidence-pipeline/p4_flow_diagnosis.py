"""Zero-network diagnostic probes; never changes P4 artifacts or claims acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import FrameType
from unittest.mock import patch

import p0_baseline

HERE = Path(__file__).resolve().parent


def investigate() -> dict[str, object]:
    network = p0_baseline.block_external()
    import p4_item_trial as trial
    from test_p4_item_trial import batch_raws, perfect_rows

    audit_path = HERE / "p4-runs/p4-items-1/audit-export.json"
    audit = json.loads(audit_path.read_text())
    assert hashlib.sha256(audit_path.read_bytes()).hexdigest() == (
        "0bcd1497e74195b6c44ec487794266fdd0749ebeb1547ee59ad093d63c883966"
    )
    calls: set[tuple[str, str]] = set()
    repo_prefix = str(trial.ROOT) + "/"

    def trace(frame: FrameType, event: str, arg: object) -> None:
        if event == "call":
            code = frame.f_code
            filename = code.co_filename
            if filename.startswith(repo_prefix) and "/.venv/" not in filename:
                calls.add((filename[len(repo_prefix):], code.co_name))

    sys.setprofile(trace)
    try:
        plan = trial.prepare()
        raw = audit["attempts"][0]["raw"]
        ids = tuple(o.obligation_id for o in plan.obligations[:8])
        parsed, errors = trial._parse_records(plan, (raw,), set(ids))
    finally:
        sys.setprofile(None)
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert len(rows) == 8 and len(parsed) == 4
    assert not trial.valid_batch_response(plan, ids, raw)
    assert not trial.valid_batch_response(plan, ids, raw)

    # Counterfactual, NOT a repair: change only the invalid semantic enum.
    corrected = json.loads(json.dumps(rows))
    for row in corrected:
        value = row["fields"]["semantic_type"]
        if value in {"risk", "question"}:
            row["fields"]["semantic_type"] = {"risk": "forecast", "question": "unknown"}[value]
    corrected_raw = "\n".join(json.dumps(row) for row in corrected)
    assert trial.valid_batch_response(plan, ids, corrected_raw)
    partial_score = trial.score(plan, (corrected_raw,), audit_complete=False)
    first_checks = partial_score["detail"][:8]
    wrong_axes = dict(Counter(
        axis for row in first_checks for axis, passed in row["checks"].items() if not passed
    ))

    projection = json.loads(trial.PROJECTION.read_text())
    synthetic = perfect_rows(plan, projection)
    synthetic_raws = batch_raws(plan, synthetic)
    assert trial.score(plan, synthetic_raws, audit_complete=True)["passed"]

    # A G2 diagnostic counterexample through score(); execute() does verify_plan.
    changed = replace(plan.obligations[0], source_text="SYNTHETIC_UNRELATED_TEXT")
    tampered = replace(plan, obligations=(changed, *plan.obligations[1:]))
    tampered_score = trial.score(tampered, synthetic_raws, audit_complete=True)
    assert tampered_score["passed"]
    try:
        trial.verify_plan(tampered)
    except ValueError:
        execute_precheck_rejects_tampered_plan = True
    else:
        execute_precheck_rejects_tampered_plan = False
    assert execute_precheck_rejects_tampered_plan

    # A label-only error satisfies the advertised G3 floor but fails G6.
    synthetic[0]["fields"]["semantic_type"] = (
        "fact" if synthetic[0]["fields"]["semantic_type"] != "fact" else "opinion"
    )
    one_axis = trial.score(plan, batch_raws(plan, synthetic), audit_complete=True)
    assert one_axis["gates"]["G3_field_semantics"] == "passed"
    assert one_axis["gates"]["G6_per_scope_non_regression"] == "failed"

    with patch.object(trial, "PROJECTION", HERE / "__absent_diagnostic_projection__.json"):
        try:
            trial.prepare()
        except FileNotFoundError:
            no_gold_prepare = "cannot_prepare_without_evaluation_projection"
        else:
            raise AssertionError("expected current planner dependency on evaluation projection")

    protected = json.loads((
        HERE / "p0-baselines/baseline-4e2c45ce216a9421/protected-paths.json"
    ).read_text())["file_sha256"]
    request = json.loads(audit["attempts"][0]["request"].split("INPUT_JSON=", 1)[1])
    return {
        "version": "p4-flow-diagnosis-1",
        "purpose": "diagnosis_only_not_acceptance_or_repair",
        "new_model_calls": 0,
        "database_connections": 0,
        "network": network,
        "original": {
            "attempted_obligations": 8,
            "returned_unique_ids": len({row["obligation_id"] for row in rows}),
            "json_valid_rows": len(rows),
            "strict_valid_rows": len(parsed),
            "first_batch_error_count": len(errors),
            "not_attempted_obligations": len(plan.obligations) - 8,
            "invalid_semantic_values": dict(Counter(
                row["fields"]["semantic_type"] for row in rows
                if row["fields"]["semantic_type"] not in trial.SEMANTIC_TYPES
            )),
        },
        "enum_only_counterfactual": {"batch_protocol_valid": True, "remaining_axis_mismatches": wrong_axes},
        "synthetic_counterexamples": {
            "tampered_text_score_passed": tampered_score["passed"],
            "execute_precheck_rejects_tampered_plan": execute_precheck_rejects_tampered_plan,
            "one_semantic_error_G3": one_axis["gates"]["G3_field_semantics"],
            "one_semantic_error_G6": one_axis["gates"]["G6_per_scope_non_regression"],
            "one_semantic_error_accuracy": one_axis["metrics"]["semantic_accuracy"],
        },
        "runtime_contract": {
            "prepare_without_gold": no_gold_prepare,
            "request_keys": sorted(request),
            "obligation_keys": sorted(request["obligations"][0]),
            "fill_field_keys": sorted(trial.FilledFields.model_fields),
            "executed_repo_files_during_prepare_and_parse": sorted({file for file, _ in calls}),
            "legacy_extractor_called": any(file.endswith("/material_semantics.py") for file, _ in calls),
            "p2_runtime_called": any(file.endswith("/_r2_runtime.py") for file, _ in calls),
            "corpus_service_called": any(file.endswith("/service.py") for file, _ in calls),
        },
        "protection": {
            "files": len(protected),
            "by_root": dict(Counter(path.split("/")[0] for path in protected)),
            "server_runs_artifacts": sum(path.startswith("server/runs/") for path in protected),
        },
        "frozen_input_sha256": {
            str(path.relative_to(trial.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (audit_path, HERE / "p4_item_trial.py", trial.PROJECTION, trial.BRIDGE_REVIEW)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = investigate()
    body = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(body)
    print(body)


if __name__ == "__main__":
    main()
