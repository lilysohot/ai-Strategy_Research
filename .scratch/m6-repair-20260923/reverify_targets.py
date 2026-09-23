from pathlib import Path
import asyncio, json, sys
from unittest.mock import patch
ROOT=Path('/home/administrator/FrontierAgent');sys.path.insert(0,str(ROOT));OUT=Path(__file__).resolve().parent
from plugins.corpus.preparation.guard import install
install(ROOT/'.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json')
from plugins.tools import get_builtin_tools
from plugins.corpus.service import CorpusService
rows=[json.loads(s) for s in (ROOT/'.scratch/m6-current-review-20260923/target-diff.jsonl').read_text().splitlines()]
env=dict(l.split('=',1) for l in (ROOT/'.env').read_text().splitlines() if '=' in l and not l.lstrip().startswith('#'))
cred=env['CORPUS_DSN'].split('://',1)[1].rsplit('@',1)[0];dsn=f'postgresql://{cred}@127.0.0.1:543/i2_sandbox_corpus'
async def main():
 result=[]
 with patch('plugins.corpus.service.dsn',return_value=dsn):
  tool=get_builtin_tools()['corpus_fetch']
  for row in rows:
   value=json.loads(await tool.ainvoke({'doc_id':row['handle'],'locator':row['locator']}))
   ok=value.get('ok') is True and ''.join(row['quote'].split()) in ''.join(value.get('text','').split())
   result.append({'query_id':row['qid'],'target':row['target'],'passed':ok,'authority_rev':value.get('authority_rev'),'context_unit_ids':value.get('context_unit_ids',[])})
 (OUT/'target-roundtrip.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False))
 if not all(r['passed'] for r in result):raise SystemExit(1)
asyncio.run(main())
