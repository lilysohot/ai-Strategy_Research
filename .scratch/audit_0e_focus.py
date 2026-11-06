import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/0e672d697711462998d52f8262e977bb')
base = root / 'run/agent/trajectories'
start = json.loads((base / 'main_agent.jsonl').read_text().splitlines()[0])['ts']
print('START', datetime.fromtimestamp(start, timezone(timedelta(hours=8))).isoformat())
print('RELEASES', [p.name for p in Path('/home/administrator/.local/state/frontier-agent/releases').glob('team-evidence-*')])
for p in sorted(base.rglob('*.jsonl')):
    rows = list(map(json.loads, p.read_text().splitlines()))
    if p.name == 'main_agent.jsonl':
        print('END', datetime.fromtimestamp(rows[-1]['ts'], timezone(timedelta(hours=8))).isoformat())
    for r in rows:
        at = round(r['ts'] - start, 2)
        if r['t'] == 'llm':
            for c in r.get('tool_calls', []):
                a = c.get('args', {})
                if c['name'] == 'add_task': print('PLAN', json.dumps(a, ensure_ascii=False))
                if c['name'] == 'submit_report' and p.name == 'independent_verifier.t05.jsonl':
                    print('FAIL', json.dumps(a, ensure_ascii=False))
        if r['t'] == 'result':
            if p.name.startswith('markets_history') and r.get('name') == 'bash':
                print('BASH', at, r['result'])
            if r.get('name') == 'corpus_submit_manifest': print('MANIFEST', r['result'])
    if p.name == 'independent_verifier.t04.jsonl':
        snap = json.loads(p.with_suffix('.json').read_text())
        inp = next(m['content'] for m in snap['messages'] if m['role'] == 'user')
        Path('/home/administrator/FrontierAgent/.scratch/audit_0e_recheck_prompt.txt').write_text(inp)
        print('RECHECK_HEADINGS', [line for line in inp.splitlines() if line.startswith('#')])
for p in (root / 'run/corpus').rglob('*verification*.json'):
    print('VERIFICATION', p.name, p.read_text()[:5000])
