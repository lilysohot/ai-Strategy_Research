"""Read-only replay of recorded tool output and verifier dispatch; no model calls."""
import json
from pathlib import Path

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.runtime.loop.tool_call_parser import MultiFormatToolCallParser
from plugins.tools._corpus_handoff import observed_corpus_evidence, evidence_identity
from plugins.tools._verification import VerificationCheck, bind_checks, set_verification_scope, reset_verification_scope, validate_results
from tests.test_agent_team_verification import add_job

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/6d4a2c7200124b2b9c91c08960133cae')
summary = json.loads((root / 'summary.json').read_text())
base = root / 'run/agent/trajectories'
bus = AgentBus()
jobs = summary['report_contract']['job_outcomes']
for job in jobs:
    if job['verification_checks']:
        continue
    trace = base / 'subagents' / (job['agent'] + '.t01.jsonl')
    rows = [json.loads(s) for s in trace.read_text().splitlines()]
    reports = [c['args']['content'] for r in rows if r['t'] == 'llm' for c in r.get('tool_calls', []) if c['name'] == 'submit_report']
    records = {}
    for row in rows:
        if row['t'] == 'result' and row.get('name') in {'corpus_search', 'corpus_fetch'}:
            try:
                payload = json.loads(row['result'])
            except (ValueError, TypeError):
                continue
            for record in observed_corpus_evidence(row['name'], payload):
                records[evidence_identity(record)] = record
    add_job(bus, job['job_id'], [])
    result = bus._jobs[job['job_id']].result
    result.final_content = reports[-1]
    result.metadata.update(content_acquisition=job['content_acquisition'], corpus_evidence=list(records.values()))

rows = [json.loads(s) for s in (base / 'main_agent.jsonl').read_text().splitlines()]
assignments = [t for r in rows if r['t'] == 'llm' for c in r.get('tool_calls', []) if c['name'] == 'assign_task' for t in c['args'].get('tasks', []) if t.get('verification_checks')]
first, recheck = assignments
specs = [VerificationCheck.model_validate(v) for v in first['verification_checks']]
plans = summary['report_contract']['task_board']
kwargs = dict(bus=bus, task_id='run', work_items=plans, required=True, outputs_root=Path('/tmp'))
checks, first_prompt = bind_checks(specs, **kwargs)
rev = VerificationCheck.model_validate(recheck['verification_checks'][0])
add_job(bus, rev.replaces_job_id, checks, verdicts=['pass', 'pass', 'fail'])
out = {'original_first_context_chars': 78998, 'original_recheck_context_chars': 65176, 'new_first_bound_context_chars': len(first_prompt)}
try:
    bind_checks([rev], **kwargs)
except ValueError as exc:
    out['recorded_recheck_rejected_before_dispatch'] = '资料库中没有' in str(exc)
    out['rejection_code'] = 'remaining_corpus_scope_overstatement'
corrected = rev.model_copy(update={'subject': type(rev.subject)(text=rev.subject.text.replace('资料库中没有任何', '本次检索未发现'))})
_, prompt = bind_checks([corrected], **kwargs)
out['corrected_recheck_bound_context_chars'] = len(prompt)
out['corrected_recheck_with_original_preamble_chars'] = len(prompt) + 1501
out['context_reduction_fraction'] = round(1 - (len(prompt) + 1501) / 65176, 4)
trace = base / 'subagents/corpus_claim_verifier.t02.jsonl'
raw = next(r for r in (json.loads(s) for s in trace.read_text().splitlines()) if r.get('t') == 'llm' and 'DSML' in (r.get('content') or ''))
calls = MultiFormatToolCallParser().parse(LLMResponse(content=raw['content']), {'submit_report'})
out['original_dsml_recovered_calls'] = len(calls)
snap = json.loads(trace.with_suffix('.json').read_text())
message = next(m['content'] for m in snap['messages'] if isinstance(m.get('content'), str) and '# Bound verification checks\n' in m['content'])
original_checks, _ = json.JSONDecoder().raw_decode(message.split('# Bound verification checks\n')[1])
for c in original_checks:
    c['subject']['text'] = rev.subject.text
token = set_verification_scope('recorded-recheck', {'verification_checks': original_checks})
try:
    validate_results(calls[0]['args']['verification_results'])
except ValueError as exc:
    out['recovered_pass_still_rejected'] = 'bounded corpus retrieval' in str(exc)
finally:
    reset_verification_scope(token)
Path('.scratch/team-repair-real-replay.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(json.dumps(out, ensure_ascii=False, indent=2))
