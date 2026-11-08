"""Archive exact-run diagnostics; model reviews never promote release status."""
import json
from pathlib import Path

from benchmarks.team_workflow.run import apply_review, digest


def inspect(folder, sample):
    trial = Path("results") / folder / sample
    if not (trial / "result.json").exists():
        return {"sample": sample, "status": "unassessed"}
    verdict = json.loads((trial / "result.json").read_text())
    metrics = json.loads((trial / "metrics.json").read_text()) if (trial / "metrics.json").exists() else {}
    worker = json.loads((trial / "worker.json").read_text()) if (trial / "worker.json").exists() else {}
    result = worker.get("result", {})
    completion_tokens = 0
    unknown_completion = 0
    delivery_errors = []
    for trace in (trial / "agent/trajectories").rglob("*.jsonl"):
        for line in trace.read_text().splitlines():
            event = json.loads(line)
            if event["t"] == "attempt" and event.get("phase") == "finished":
                usage = event.get("usage") or {}
                if "completion_tokens" in usage:
                    completion_tokens += usage["completion_tokens"] or 0
                else:
                    unknown_completion += 1
            if event["t"] == "result" and event.get("name") == "deliver_answer" and event.get("error"):
                delivery_errors.append(event.get("result"))
    return {
        "sample": sample, **verdict,
        "metrics": {k: metrics.get(k) for k in ["attempts", "known_prompt_tokens", "known_cache_read_tokens", "first_research_report_s", "failure_reasons", "tools"]},
        "known_completion_tokens": completion_tokens, "unknown_completion_attempts": unknown_completion,
        "final_chars": len(result.get("final_answer", "")), "delivery_errors": delivery_errors,
    }


def review(folder, sample, scores):
    out = Path("results") / folder
    trial = out / sample
    result = json.loads((trial / "result.json").read_text())
    if result.get("review_file") or result["status"] != "needs_review":
        return
    payload = {
        "reviewer": "Codex artifact review, 2026-11-07", "review_type": "model",
        "worker_sha256": digest(json.loads((trial / "worker.json").read_text())),
        "case_sha256": digest(json.loads((trial / "input.json").read_text())),
        "criteria": [{"verdict": verdict, "evidence": evidence} for verdict, evidence in scores],
    }
    target = Path(".scratch") / f"{folder}-{sample}-review.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    apply_review(out, sample, target)


review("team-efficiency-standard", "F12-r1", [
    ("pass", "final_answer gives 4*5+2*12=44 yuan from the actually retrieved supplied prices."),
    ("pass", "answer_status complete; no tax/shipping or brand data blocks the goods subtotal."),
    ("fail", "Despite 算式即可, final_answer contains RFC/domain commentary, repeated arithmetic and a verification explanation; no automatic appendix is appended now, but model prose still fails compactness."),
    ("pass", "Bound arithmetic check passes with recomputation, and final_answer explicitly excludes tax/shipping."),
])
review("team-efficiency-standard", "F13-r1", [
    ("pass", "final_answer says 44 yuan is a subtotal and the inclusive amount is indeterminate."),
    ("pass", "final_answer identifies missing tax and shipping and asks for these inputs."),
    ("fail", "report_contract marks every task resolved and answer_status complete; t2 defines its own alternative completion as providing the result OR explaining why unavailable, and moves the missing requested inclusive total into limitations."),
    ("fail", "Answer adds optional brand/origin comparison, RFC/domain commentary, and repeated verification prose; researcher/verifier also re-fetch the same exact source."),
])
review("team-efficiency-standard", "F15-r1", [
    ("pass", "final_answer gives December 9, matching the actually fetched backup."),
    ("pass", "notice_lookup_research trace fetches primary first, then backup only after returned unavailable results; no speculative parallel primary/backup call."),
    ("pass", "Backup content was actually acquired after primary failures, not inferred from a search snippet."),
    ("fail", "User asks only the date; answer adds failed-attempt counts, repeated-fetch diagnostics, a missing-year qualification and unsupported concern about incomplete page inspection."),
])
review("team-efficiency-standard", "F17-r1", [
    ("pass", "Successful retry reads the fee page and gives 30 yuan * 2 = 60 yuan."),
    ("pass", "event-fee_research.t02 calls web_fetch for notice at line 4, observes no fee, then fetches fee page at line 9."),
    ("pass", "Readable notice does not terminate acquisition; required fee evidence is obtained before calculating the answer."),
    ("fail", "Final body adds unrelated membership/early-bird/group-rate exclusions, missing currency-code/version commentary and internal retry notes. It also remains partial because the first required job failed, despite successful replacement research; that requires explicit retry lineage rather than hiding the failure."),
])

folders = {
    "baseline": ("team-scope-standard-after", ["F12", "F13", "F14"]),
    "initial_after": ("team-efficiency-standard", ["F12", "F13", "F14", "F15", "F16", "F17"]),
    "goal_refinement": ("team-efficiency-goal-refinement", ["F13"]),
}
record = {
    "date": "2026-11-07",
    "scope": "General delegation boundaries, conditional fallback, delivery protocol rework, and audit presentation. No context-compaction or verifier-count change.",
    "acceptance": "Code regressions pass; model semantics and reliability require separate assessment, not automatic release approval.",
    "baseline_lock": "benchmarks/team_workflow/baseline-59.lock.json",
    "catalog": {"total": 66, "protocol": 49, "frozen": 17, "new": ["P46", "P47", "P48", "P49", "F15", "F16", "F17"], "public_transfer_not_blind_holdout": True},
    "changes": [
        "Shared general assignment policy links investigation to requested results/evidence, forbids speculative conditional alternatives, and keeps irrelevant audit prose out of answers.",
        "web_fetch fallback_urls executes bounded alternatives sequentially after explicit failure/partial/empty content; independent URL batches remain parallel, policy denial stops fallback. Captured source identity survives fallback.",
        "Coordinator tool visibility withholds deliver_answer while member work/required checks need coordination; exact passed publication passages are offered for reuse without weakening byte/version gates.",
        "Automatic passed-check hashes and acquisition-attempt footers move to the audit contract; necessary failures and gaps remain visible, with exact duplicate gaps suppressed.",
        "Authorized redacted audit endpoint and lazy Web audit tab expose checks/limits independently of the answer, including absent-record state.",
        "F13 exposed self-written alternative completion criteria; a subsequent general policy/schema clarification anchors done_when and delivery to the original requested outcome. Initial failing artifacts are preserved.",
    ],
    "validation": {
        "targeted_pytest": {"passed": 178, "artifact": ".scratch/team-efficiency-all-targeted.txt"},
        "initial_red": ".scratch/team-efficiency-red.txt",
        "protocol": {"pass": 45, "fail": 4, "remaining": ["P34", "P35", "P36", "P37"], "artifact": "results/team-efficiency-protocol/summary.json"},
        "lint": ".scratch/team-efficiency-lint.txt", "scoped_types": "0 errors",
        "full_types": "15 errors in previously failing files; not a green repository-wide type gate",
        "web_build": "passed Vue typecheck and Vite build; existing large-chunk warning",
        "browser": "Isolated real Vue component/API client tested in headless Windows Edge with fixed HTTP audit responses: detail, collapse, run switch, absent record. Linux browser attempt could not start due to missing libnspr4.",
        "browser_script": ".scratch/verify-team-audit.cjs", "browser_image": ".scratch/team-efficiency-audit.png",
        "import_smoke": ["466/466", "525/525"], "symbols": "0 missing / 574 files", "provider_preflight": "passed",
        "audit_replay": json.loads(Path(".scratch/team-efficiency-replay.json").read_text()),
    },
    "model_runs": {label: {"directory": "results/" + folder, "profile": "tui", "samples": [inspect(folder, case + "-r1") for case in cases]} for label, (folder, cases) in folders.items()},
    "limitations": [
        "Model review stays needs_review; no model diagnostic is labeled human acceptance.",
        "One run per case is insufficient for a stable latency/cost or causal-regression claim. Prompt tokens include cached input; no currency cost is inferred.",
        "An optional fallback interface cannot mechanically detect or prevent every semantically conditional call made outside it. General delegation relevance and task satisfaction still depend on model behavior.",
        "Provider empty-tool-argument recovery remains observed; required arguments already existed in the schema. No fabricated dispatch arguments or relaxed finalization gate were introduced.",
        "F17 exposes failed required research-job lineage remaining blocking after a successful retry. This change does not silently waive the earlier failure or implement research replacement lineage.",
        "One legacy display assertion moved from answer prose to the audit contract because presentation requirements changed; source preservation assertions remain.",
        "No full frozen-suite, blinded or live authenticated Web research evaluation, deployment, service restart or commit was performed.",
    ],
}
path = Path("benchmarks/team_workflow/REPAIR-EFFICIENCY-2026-11-07.json")
path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
print(path)
