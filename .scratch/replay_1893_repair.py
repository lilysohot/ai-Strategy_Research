"""Read-only replay of Web run 18937; no model, network, or run mutation."""

import json
from pathlib import Path

from frontier_agent.components.agent_bus import AgentBus
from plugins.tools._verification import VerificationCheck, bind_checks
from tests.test_agent_team_verification import add_job


ROOT = Path(
    "/home/administrator/.local/share/frontier-agent/web/runs/"
    "18937dbdabb1401296a685aeaa747c0b"
)
TEAM = ROOT / "run/agent/team-results/1b783b2d4605"
TRACE = ROOT / "run/agent/trajectories/main_agent.jsonl"

summary = json.loads((ROOT / "summary.json").read_text())
bus = AgentBus()
for index in (1, 2, 3):
    job_id = f"1b783b2d4605.job.{index}"
    saved = json.loads((TEAM / f"{job_id}.json").read_text())
    add_job(bus, job_id, [])
    result = bus._jobs[job_id].result
    result.final_content = saved["final_content"]
    result.metadata.update(saved["metadata"])

rows = [json.loads(line) for line in TRACE.read_text().splitlines()]
assignments = [
    task
    for row in rows
    if row["t"] == "llm"
    for call in row.get("tool_calls", [])
    if call["name"] == "assign_task"
    for task in call["args"].get("tasks", [])
    if task.get("verification_checks")
]
first = assignments[0]
recheck = assignments[1]
first_specs = [VerificationCheck.model_validate(value) for value in first["verification_checks"]]
kwargs = {
    "bus": bus,
    "task_id": "run",
    "work_items": summary["report_contract"]["task_board"],
    "required": True,
    "outputs_root": Path("/tmp"),
}
first_bound, _ = bind_checks(first_specs, **kwargs)
prior = json.loads((TEAM / "1b783b2d4605.job.4.json").read_text())
add_job(bus, "1b783b2d4605.job.4", first_bound)
bus._jobs["1b783b2d4605.job.4"].item.metadata["verification_events"] = prior[
    "assignment_metadata"
]["verification_events"]

recheck_specs = [
    VerificationCheck.model_validate(value) for value in recheck["verification_checks"]
]
_, prompt = bind_checks(recheck_specs, **kwargs)
needle = "2026年海外AI短剧全年规模约6.5亿美元"
assert needle in prompt
assert '"source_job": "1b783b2d4605.job.2"' in prompt
assert '"text_excerpt": true' in prompt
out = {
    "recheck_prompt_chars": len(prompt),
    "industry_direct_evidence_delivered": needle in prompt,
    "industry_source_attributed": '"source_job": "1b783b2d4605.job.2"' in prompt,
    "focused_exact_excerpt_used": '"text_excerpt": true' in prompt,
}
print(json.dumps(out, ensure_ascii=False, indent=2))
