"""Capture the completed expansion baseline without changing any verdict."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((root / path).read_text())


protocol_path = "results/team-49e-3d877-protocol-baseline"
frozen_path = "results/team-49e-3d877-frozen-baseline"
protocol = read(f"{protocol_path}/summary.json")
frozen = read(f"{frozen_path}/summary.json")
assert len(protocol["samples"]) == 38
assert len(frozen["samples"]) == 3
assert all(s["status"] != "missing" for s in frozen["samples"])
samples = []
for sample in frozen["samples"]:
    folder = f"{frozen_path}/{sample['sample']}"
    metrics = read(f"{folder}/metrics.json")
    worker = read(f"{folder}/worker.json")
    samples.append({
        **sample,
        "artifacts": folder,
        "source": read(f"{folder}/source.json"),
        "metrics": {k: metrics.get(k) for k in (
            "attempts", "known_prompt_tokens", "unknown_usage_attempts",
            "max_prompt_tokens", "exact_repeated_tool_requests",
        )},
        "stopped_by": worker["result"].get("stopped_by"),
        "llm_error_reason": worker["result"].get("llm_error_reason"),
    })

record = {
    "date": "2026-11-06",
    "scope": "Incremental benchmark expansion and failure baseline only; no production fixes or deployment in this round.",
    "origins": ["49e4f04b05ca46fda0ae4e4b71d1636a", "3d87700083864a1dbb41acfa74f46136"],
    "catalog": {
        "total": 48, "protocol": 38, "frozen": 10,
        "historical_cases_preserved": 40,
        "lock": "benchmarks/team_workflow/baseline-40.lock.json",
        "new_cases": ["P34", "P35", "P36", "P37", "P38", "F08", "F09", "F10"],
        "blind_holdout_created": False,
    },
    "protocol": {
        "artifacts": protocol_path,
        "states": protocol["states"],
        "historical_P01_P33_all_pass": all(s["status"] == "pass" for s in protocol["samples"] if int(s["case"][1:]) <= 33),
        "failures": [s for s in protocol["samples"] if s["status"] != "pass"],
        "raw_probe_repeats": {"runs": 2, "each_failed": 6, "each_passed": 6, "xfail_used": False},
    },
    "frozen": {
        "artifacts": frozen_path, "states": frozen["states"], "samples": samples,
        "model_reviews_are_diagnostic_only": True,
        "artifact_observations": {
            "F08": "Completed. Model review passes three factual/coverage criteria but fails concise useful scope: duplicated retrieval, HTTP/DNS diversion and unsolicited calendar/arithmetic work. Official status remains needs_review, not pass.",
            "F09": "Execution error: main turn 7 received no streamed chunks for about 120 seconds and ended logical_call_deadline. Fallback answer retains the four supported figures, but adds lengthy access and arithmetic discussion plus unresolved-board notices. Independent verifier returned four scoped PASS checks; these do not override execution failure.",
            "F10": "Execution error: main turn 14 received no streamed chunks for about 120 seconds and ended logical_call_deadline. Partial final answer correctly keeps Arbor at its September acceptance scope, Birch unknown, plan fulfillment unsupported, and November absence limited to this query. This useful partial answer is not an end-to-end pass.",
        },
        "all_10_frozen_cases_rerun": False,
        "fingerprint_note": "F08 was started before a test-only Optional-result assertion was added in regression_probes.py; F09/F10 after. Source fingerprints therefore differ. Production runtime, prompts, model settings, cases and fixture bodies were not changed during these runs. Do not label them byte-identical source snapshots.",
    },
    "checks": {
        "evaluator_integrity_pytest": "24 passed",
        "scoped_ruff": "passed",
        "scoped_pyright_benchmarks_team_workflow": "0 errors",
        "full_pyright": {"status": "failed", "errors": 15, "files_not_modified_this_round": ["deploy/huggingface/app.py", "plugins/corpus/service.py", "scripts/run_retention.py", "server/watch_scheduler.py"], "log": ".scratch/team-49e-3d877-pyright-final.txt"},
        "import_smoke_stage_1": "465/465 passed",
        "import_smoke_stage_2": "524/524 passed",
        "symbol_closure": "0 missing across 573 files",
        "real_provider_preflight": "passed",
    },
    "next_repair_acceptance": [
        {"layer": "tool protocol and verification", "cases": ["P34", "P35", "P36", "F08", "F09"], "target": "Validate every submitted calculation receipt and bind required claims to source scope; missing facts or table periods cannot be certified by unrelated evidence. Preserve positive controls."},
        {"layer": "team orchestration and recovery", "cases": ["P37"], "target": "Settle obligations against successful replacement checks while retaining failed history; incomplete replacement must still block completion."},
        {"layer": "context, synthesis and execution cost", "cases": ["P38", "F08", "F09", "F10"], "target": "Carry evidence limits into the final answer and avoid unsupported task expansion or repeated retrieval; retain error samples and missing usage rather than selecting only successes."},
    ],
    "limitations": [
        "Known failure replays and visible transfer controls are not an unseen holdout.",
        "Protocol probes establish these concrete acceptance defects, not general natural-language reasoning correctness; regex-only repairs are not prescribed.",
        "Fixed web fixtures do not test real corpus ranking, table reconstruction or live retrieval latency.",
        "Retrieval DB, embedding, rerank and queue timing remain unmeasured; overlapping tool durations are not additive wall time.",
        "DNS and HTTP-variant diversions may partly reflect synthetic fixture presentation; check live-tool traces before attributing all such behavior to general production retrieval.",
        "Single samples per new case cannot estimate stable failure rates or calibrated SLOs; model review cannot certify release acceptance.",
        "The repeated-request metric compares exact complete tool arguments; repeated individual URLs inside changed batches need trajectory review.",
        "Old frozen cases retain their original criteria and budgets but were not all executed in this round.",
    ],
}
destination = root / "benchmarks/team_workflow/BASELINE-49E-3D877-2026-11-06.json"
destination.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
print(destination)
