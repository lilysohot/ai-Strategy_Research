import json
from pathlib import Path
from collections import Counter
from plugins.tools._corpus_scope import corpus_scope_findings

root=Path('/home/administrator/.local/share/frontier-agent/web/runs/6d4a2c7200124b2b9c91c08960133cae')
s=json.loads((root/'summary.json').read_text())
c=s['report_contract']
print('REPLAY',s.get('replay'))
print('CONTRACT CHECKS')
for check in c['verification_checks']:
    print('CHECK',check.get('check_id'),check.get('verdict'),check.get('execution_status'))
    if check['check_id']=='attribution':
        text=check['subject']['text']
        obs=[o for source in [check['subject'],*check['evidence']] for o in source.get('corpus_limits',[])]
        print('SUBJECT',text)
        print('MATCHES',json.dumps(corpus_scope_findings(text,obs),ensure_ascii=False))
print('FINAL_BOUNDARY',json.dumps(s.get('evidence_boundary'),ensure_ascii=False)[:4000])
base=root/'run/agent/trajectories'
for p in sorted(base.rglob('*.jsonl')):
    rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    attempts=[r for r in rows if r['t']=='attempt' and r.get('phase')=='finished']
    usage=[r['usage'] for r in attempts if r.get('usage')]
    print('AGENT',p.stem,'input',sum(u.get('prompt_tokens',0) for u in usage),
          'output',sum(u.get('completion_tokens',0) for u in usage),
          'first_input',usage[0].get('prompt_tokens') if usage else None,
          'max_input',max((u.get('prompt_tokens',0) for u in usage),default=0),
          'llm_s',round(sum(r.get('duration_ms',0) for r in attempts)/1000,3))
    snap=json.loads(p.with_suffix('.json').read_text())
    print('CONFIG',p.stem,'max_turns',snap.get('max_turns'))
    if 'verifier' in p.stem:
        m=snap['messages'][1]['content']
        begin=m.find('# Bound verification checks')
        source=m.find('SOURCE ')
        handoff=m.find('# Tool-delivered corpus evidence')
        print('CONTEXT_SIZES','total',len(m),'preamble',begin,'binding_and_rules',source-begin,'reports',handoff-source,'original_handoff',len(m)-handoff)
    if p.stem=='main_agent':
        for r in rows:
            if r['t']=='llm':
                for call in r.get('tool_calls',[]):
                    if call['name']=='deliver_answer':
                        args=call['args']
                        print('DELIVERY',r['turn'],'chars',len(args['content']), 'manifest_count',len(args.get('corpus_conclusions',[])))
            if r['t']=='start':
                print('START',json.dumps(r,ensure_ascii=False)[:1500])
print('RUN_ROOT_FILES',[(str(p.relative_to(root/'run')),p.stat().st_size) for p in (root/'run').iterdir() if p.is_file()])
