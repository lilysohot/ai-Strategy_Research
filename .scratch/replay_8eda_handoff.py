"""Read-only replay of recorded source tools through the repaired handoff seam."""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path('/home/administrator/FrontierAgent')
sys.path.insert(0, str(ROOT))
from frontier_agent.components.agent_bus import AgentBus, JobEntry, SubTask, SubAgentResult
from frontier_agent.core.loop_types import AgentLoopResult, ToolResult
from plugins.tools._verification import VerificationCheck, bind_checks, render_verification_status
from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver
from plugins.corpus.search_refs import canonical_locator

RUN = Path('/home/administrator/.local/share/frontier-agent/web/runs/8eda75f47314494ea7a03c020dd219bb')

async def build():
    summary = json.loads((RUN/'summary.json').read_text())
    base = RUN/'run/agent/trajectories'
    task_id = json.loads((base/'main_agent.jsonl').read_text().splitlines()[0])['task_id']
    bus = AgentBus()
    total = 0
    for entry in summary['report_contract']['job_outcomes'][:2]:
        path = next(base.rglob(entry['agent']+'.t01.jsonl'))
        observer = ContentAcquisitionObserver()
        ctx = SimpleNamespace(metadata={})
        report = ''
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row['t'] == 'result' and row.get('name') in {'corpus_search','corpus_fetch'}:
                await observer.on_tool_result(ctx, ToolResult(name=row['name'], args=row.get('args',{}),
                    result=row['result'], duration_ms=0, tool_call_id='replay', is_error=row.get('is_error',False)))
            if row['t'] == 'llm':
                for call in row.get('tool_calls',[]):
                    if call['name'] == 'submit_report':report = call['args']['content']
        result = AgentLoopResult(messages=[], final_content=report)
        await observer.on_loop_end(result)
        total += len(result.metadata.get('corpus_evidence',[]))
        bus._jobs[entry['job_id']] = JobEntry(job_id=entry['job_id'], parent_task_id=task_id,
            status='completed', item=SubTask(question='Recorded research'),
            result=SubAgentResult(question='Recorded research', role_id='researcher',
                final_content=report, success=True, job_id=entry['job_id'], metadata=result.metadata))
    rows=[json.loads(x) for x in (base/'main_agent.jsonl').read_text().splitlines()]
    dispatch = next(r for r in rows if r['t']=='llm' and r['turn']==11)['tool_calls'][0]['args']['tasks'][0]
    specs = [VerificationCheck.model_validate(c) for c in dispatch['verification_checks']]
    checks, prompt = bind_checks(specs, bus=bus, task_id=task_id,
        work_items=summary['report_contract']['task_board'], required=True, outputs_root=ROOT)
    job = 'replayed-verifier'
    bus._jobs[job] = JobEntry(job_id=job, parent_task_id=task_id, status='running',
        item=SubTask(question='Check', metadata={'verification_checks':checks}))
    status = render_verification_status(bus, task_id)
    previous_prompt=json.loads(next(base.rglob('claim_verifier.t01.json')).read_text())['messages'][1]['content']
    previous_status=next(r for r in rows if r['t']=='result' and r.get('name')=='collect_reports'
                         and '[version-bound checks]' in r.get('result',''))['result']
    # Resolving a stored search ref is local and read-only; it does not fetch sources.
    os.environ['CORPUS_SEARCH_REF_ROOT'] = str(RUN/'run/corpus/search-refs')
    receipt = next((RUN/'run/corpus/search-refs').glob('*.json'))
    os.environ['CORPUS_TARGET_DB'] = json.loads(receipt.read_text())['target']
    verified = errors = 0
    for entry in bus.list_task_jobs(task_id):
        if not entry.result:continue
        for item in entry.result.metadata.get('corpus_evidence',[]):
            if item['locator'].startswith('eref:') and item['locator'] in prompt:
                try:
                    assert canonical_locator(item['doc_id'], item['locator']).startswith('chunk:native1/')
                    verified += 1
                except ValueError: errors += 1
    stats = {'records_captured':total, 'old_assignment_chars':len(previous_prompt),
             'new_bound_prompt_chars':len(prompt), 'old_collect_chars':len(previous_status),
             'new_status_chars':len(status), 'resolvable_search_refs':verified,'invalid_search_refs':errors,
             'limitations':'Recorded-tool replay, not a full new research run'}
    out = ROOT/'.scratch/verification-recovery'
    (out/'handoff_prompt.txt').write_text(prompt)
    (out/'handoff_replay.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    print(json.dumps(stats))
    assert len(prompt) < len(previous_prompt)/2 and len(status)<5000
    assert verified > 0 and errors == 0
    return bus, checks, prompt, task_id

if __name__ == '__main__': asyncio.run(build())
