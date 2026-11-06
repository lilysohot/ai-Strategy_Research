import json
from pathlib import Path
from types import SimpleNamespace

from frontier_agent.core.runtime.loop.tool_call_parser import MultiFormatToolCallParser

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/6d4a2c7200124b2b9c91c08960133cae')
trace = root / 'run/agent/trajectories/subagents/corpus_claim_verifier.t02.jsonl'
for line, raw in enumerate(trace.read_text().splitlines(), 1):
    row = json.loads(raw)
    content = row.get('content') or ''
    if row.get('t') == 'llm' and isinstance(content, str) and 'DSML' in content:
        response = SimpleNamespace(content=content, tool_calls=row.get('tool_calls') or [])
        parsed = MultiFormatToolCallParser().parse(response, {'submit_report'})
        print(json.dumps({'line': line, 'turn': row.get('turn'), 'native_calls': len(row.get('tool_calls') or []), 'fallback_calls': len(parsed), 'contains_submit_report': 'invoke name="submit_report"' in content, 'prefix': content[:140]}, ensure_ascii=False))
summary = json.loads((root / 'summary.json').read_text())
print('SUMMARY', {key: summary.get(key) for key in ['duration_s', 'answer_status', 'stopped_by', 'error']})
manifest = json.loads((root / 'run/corpus/manifest_verification.json').read_text())
print('MANIFEST', {key: manifest.get(key) for key in ['status', 'counts', 'verification_errors', 'boundary_answer_status', 'all_offered_fetched']})
