import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter

ROOT = Path('/home/administrator/.local/share/frontier-agent/web/runs/bf9d5de507b54b519173c08c1746cb71')
r = ROOT / 'run/agent'
main = json.loads((r / 'trajectories/main_agent.json').read_text())
print('QUESTION', [(m.get('content') or '')[:2000] for m in main['messages'] if m.get('role') == 'user'][:1])
for name in ['market_fact_check.t01', 'market_fact_check.t02', 'market_fact_check.t03']:
    j = json.loads((r / f'trajectories/subagents/{name}.json').read_text())
    for m in j['messages']:
        content = m.get('content') or ''
        if not isinstance(content, str) or '# Tool-delivered web evidence' not in content:
            continue
        print('PROMPT', name, 'chars', len(content), 'omitted', content.count('"text_omitted": true'), 'excerpt', content.count('"text_excerpt": true'))
        sec = content.split('# Tool-delivered web evidence')[1]
        lines = sec.splitlines()
        for i, line in enumerate(lines):
            if line.startswith('{') and 'cnbc.com' in line:
                print('POINTER', line)
                following = []
                for nextline in lines[i+1:]:
                    if nextline.startswith('{') and 'source_job' in nextline:
                        break
                    following.append(nextline)
                print('BODY CHARS', len('\n'.join(following)), 'BODY', '\n'.join(following)[:2200])
for p in (r / 'team-results').rglob('*job.3.json'):
    j = json.loads(p.read_text())
    for rec in j['metadata']['web_evidence']:
        print('SOURCE', rec['source'], len(rec['text']), rec.get('content_kind'))
        if 'cnbc' in rec['source']:
            print(rec['text'][:2200])
print('START LOCAL', datetime.fromtimestamp(1793953592.9463856, timezone(timedelta(hours=8))))
for p in [r / 'trajectories/main_agent.jsonl', *sorted((r / 'trajectories/subagents').glob('*.jsonl'))]:
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    if p.stem == 'main_agent':
        for row in rows:
            if row.get('t') == 'llm':
                for call in row.get('tool_calls', []):
                    if call['name'] in {'assign_task', 'deliver_answer'}:
                        args = call.get('args', {})
                        print('COORD', row.get('turn'), call['name'], str(args)[:1800] if call['name']=='assign_task' else 'content_chars='+str(len(args.get('content',''))))
    for row in rows:
        if row.get('t') == 'result':
            result = str(row.get('result', ''))
            if any(s in result for s in ['Error:', 'preflight failed', 'validation error', 'extra_forbidden']):
                print('TOOL_ERROR', p.stem, row.get('name'), result[:1200])
