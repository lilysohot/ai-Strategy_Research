"""Record artifact-bound model diagnostics without promoting release verdicts."""
import json
from pathlib import Path

from benchmarks.team_workflow.run import apply_review, digest


def review(folder, sample, criteria, observations):
    out = Path("results") / folder
    trial = out / sample
    worker = json.loads((trial / "worker.json").read_text())
    case = json.loads((trial / "input.json").read_text())
    payload = {
        "reviewer": "Codex artifact inspection, 2026-11-07",
        "review_type": "model",
        "worker_sha256": digest(worker),
        "case_sha256": digest(case),
        "criteria": [{"verdict": verdict, "evidence": evidence} for verdict, evidence in criteria],
        "additional_observations": observations,
    }
    path = Path(".scratch") / f"{folder}-{sample}-review.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    apply_review(out, sample, path)


f12 = [
    ("pass", "worker.result.final_answer gives 4×5+2×12=44元 and identifies 商品金额; input.sources supplies 5 and 12."),
    ("pass", "result.answer_status=complete; report_contract task board has resolved outcomes with empty gaps; tax/shipping absence is a nonblocking boundary."),
    ("fail", "User requests 算式即可, but final_answer adds repeated arithmetic, extensive evidence/verification sections, .invalid domain commentary and hash/version footers. Compact delivery criterion fails."),
    ("pass", "Bound arithmetic check contains recomputation; final_answer explicitly excludes tax and shipping and does not claim an exact delivered total."),
]
for folder in ("team-scope-runtime-prices", "team-scope-standard-after"):
    review(folder, "F12-r1", f12, ["Correct completion classification does not establish acceptable efficiency or concise presentation."])

f13 = [
    ("pass", "final_answer identifies 44元 as merchandise subtotal and says the tax/shipping-inclusive amount is indeterminate."),
    ("pass", "Task t2 remains blocked with a gap identifying absent tax and shipping inputs; answer_status=partial."),
    ("pass", "No assumed zero tax/free shipping; required missing operands are not downgraded to limitations or a complete answer."),
    ("pass", "Provides useful 20+24=44 calculation. Standard trace fetches the exact fixture once plus the bare host; no repeated fetch of the same fixture or brand/industry research."),
]
review("team-scope-standard-after", "F13-r1", f13, [
    "Bare-host fetch was unnecessary. Answer remains verbose and repeats gaps through automatic execution-status footer; the existing fourth rubric does not measure that verbosity.",
])
research_f13 = list(f13)
research_f13[3] = ("fail", "final_answer and retrieval trace record http/https trailing-slash variants and a search for the same supplied fixture, despite the exact URL returning all provided terms. Useful subtotal survives, but the no-meaningless-repeat criterion is not satisfied.")
review("team-scope-runtime-prices", "F13-r1", research_f13, [
    "A check asking to confirm a grand total is marked PASS while its subject says the grand total is indeterminate. Task remains partial, but criterion/subject semantic alignment needs a separate regression.",
])
review("team-scope-standard-after", "F14-r1", [
    ("pass", "final_answer translates Tuesday at 3 p.m., Room 204 and bring your draft as 周二下午3点、204室、携带你的初稿; source body was actually fetched."),
    ("pass", "No invented calendar date or timezone conversion; no host/building identity is made a prerequisite."),
    ("pass", "Delivers one translation; no meeting arrangements, institution investigation or alternative rewritten versions. Extra source-domain commentary is recorded separately rather than silently changing this rubric."),
    ("pass", "Task board resolves both retrieval and translation with empty gaps; absent background and failed http variant stay nonblocking; answer_status=complete."),
], [
    "Answer still adds a comparison table, missing-background list, invitation to resubmit, domain/RFC discussion and acquisition footer. This rubric passing does not mean the general concision objective passes.",
    "An http URL variant was fetched unnecessarily. Public synthetic fixtures may invite .invalid-domain discussion; unseen real-tool cases remain necessary.",
])

folders = ["team-scope-frozen-after", "team-scope-runtime-translation", "team-scope-runtime-prices", "team-scope-standard-after"]
runs = []
for folder in folders:
    out = Path("results") / folder
    manifest = json.loads((out / "manifest.json").read_text())
    samples = []
    for trial in sorted(out.glob("F*-r*")):
        if not (trial / "result.json").exists():
            samples.append({"sample": trial.name, "status": "unassessed"})
            continue
        result = json.loads((trial / "result.json").read_text())
        metrics = json.loads((trial / "metrics.json").read_text()) if (trial / "metrics.json").exists() else {}
        samples.append({"sample": trial.name, **result, "attempts": metrics.get("attempts"), "known_prompt_tokens": metrics.get("known_prompt_tokens")})
    runs.append({"directory": str(out), "profile": manifest.get("profile"), "samples": samples})

record = {
    "date": "2026-11-07",
    "scope": "General requirement boundaries and completion consistency; no task-category routing or special document-lookup template.",
    "overall_acceptance": "partial: contract/runtime checks pass; end-to-end concision and efficiency not accepted",
    "changes": [
        "Shared coordinator/member/reviewer policy distinguishes user outcome, necessary support, optional enrichment using existing done_when and assignment text.",
        "Persist nonblocking limitations separately from blocking gap; atomically reject resolved plus a nonempty gap; failed or unchecked mandatory verification still blocks.",
        "Delivery admission and finalization share the planning prerequisite check, preventing deliver-only lockout before a required verifier can be dispatched.",
    ],
    "red_evidence": [".scratch/team-scope-red.txt", ".scratch/team-scope-runtime-red.txt"],
    "benchmark": {"total": 59, "protocol": 45, "frozen": 14, "original_53_unchanged": True, "lock": "benchmarks/team_workflow/baseline-53.lock.json", "new_cases": ["P43", "P44", "P45", "F12", "F13", "F14"], "public_transfer_not_blind_holdout": True},
    "validation": {
        "focused": {"passed": 130, "artifact": ".scratch/team-scope-final-focused.txt"},
        "eval_integrity_and_scope": {"passed": 34, "artifact": ".scratch/team-scope-final-eval.txt", "overlaps_focused": True},
        "protocol": {"pass": 41, "fail": 4, "remaining_failure_cases": ["P34", "P35", "P36", "P37"], "artifact": "results/team-scope-runtime-protocol/summary.json"},
        "scoped_ruff": "passed", "scoped_pyright": "0 errors", "full_pyright": "15 errors in untouched files; not a clean repository-wide type gate",
        "import_smoke": ["466/466", "525/525"], "symbol_closure": "0 missing, 574 files", "provider_preflight": "passed",
        "web_cli_parity": "5 failures at mock-provider research-intake JSON parsing, before workflow execution; not fixed or baseline-bisected in this change",
    },
    "model_runs": runs,
    "configuration_note": "Default benchmark profile uses research prompts; the Web uses profile tui with standard prompts. Results are separated, not presented as a paired performance improvement.",
    "review_policy": "Artifact-bound model reviews preserve needs_review; diagnostic pass is not human acceptance or a green release gate.",
    "remaining_issues": [
        "All standard samples returned without execution errors and classified completion correctly, but F12 fails compact-answer rubric; F13/F14 rubric passes do not cover all observed verbosity.",
        "Members/coordinator still add unrelated domain investigation and audit prose; final_report also appends detailed verification/execution metadata. Scope prompts alone do not solve presentation or latency.",
        "Research-config trials include model logical-call timeouts. Shared prerequisite fix resolves a demonstrated controller deadlock, not all timeouts.",
        "Semantic classification remains model-declared. Research F13 exposes criterion/subject alignment risk despite a correct partial status.",
        "Earlier P34-P37 regressions remain red; prior invalid-locator whole-document absence and false verbatim issues are not repaired by this scope change.",
        "No full frozen-suite rerun, blinded evaluation, live Web end-to-end run, deployment, restart or commit performed for this change.",
    ],
}
path = Path("benchmarks/team_workflow/REPAIR-SCOPE-2026-11-07.json")
path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
print(path)
for run in runs:
    print(run["directory"], [(s["sample"], s.get("status"), s.get("elapsed_s"), s.get("diagnostic_verdict")) for s in run["samples"]])
