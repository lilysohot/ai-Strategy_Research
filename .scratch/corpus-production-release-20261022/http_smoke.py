"""Authenticated read-only HTTP probes; short-lived token stays in memory."""
import json
import time
from pathlib import Path

import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()
from server.config import get_config
from server.security import create_access_token

HERE=Path(__file__).parent
cfg=get_config()
with psycopg.connect(cfg.database_url.replace('postgresql+asyncpg://','postgresql://',1)) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    uid=conn.execute("SELECT id FROM users WHERE status='active' ORDER BY created_at LIMIT 1").fetchone()[0]
token=create_access_token(uid,ttl_s=120)
query='DeepSeek通过哪些训练和推理设计降低计算成本？'
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=25,headers={'Authorization':'Bearer '+token}) as client:
    state=client.get('/api/corpus/status');state.raise_for_status()
    assert state.json()['target_db']=='postgres' and state.json()['read_chain']=='new'
    t=time.monotonic();response=client.get('/api/corpus/search',params={'query':query});response.raise_for_status()
    cold_ms=round((time.monotonic()-t)*1000);payload=response.json()
    assert payload['hits'] and payload['coverage']['retrieval_mode']=='hybrid',payload.get('coverage')
    assert payload['coverage']['native']['sources']==23
    assert payload['coverage']['native']['body_characters']<=16000
    fetches=[]
    for hit in payload['hits'][:2]:
        response=client.get('/api/corpus/documents/'+hit['doc_id'],params={'locator':hit['locator']})
        response.raise_for_status();body=response.json()
        assert body['text'] and body['locator']==hit['locator']
        fetches.append({'doc_id':hit['doc_id'],'locator':hit['locator'],'characters':len(body['text'])})
    t=time.monotonic();large=client.get('/api/corpus/search',params={'query':query,'limit':50});large.raise_for_status()
    warm_ms=round((time.monotonic()-t)*1000)
    assert large.json()['coverage']['native']['block_limit']==20
    assert large.json()['coverage']['retrieval_mode']=='hybrid'
    result={'target':'postgres','query':query,'mode':payload['coverage']['retrieval_mode'],'sources':23,'hits':len(payload['hits']),'body_characters':payload['coverage']['native']['body_characters'],'cold_search_ms':cold_ms,'warm_search_ms':warm_ms,'http_limit_50_preserves_block_budget':True,'fetches':fetches,'healthz':client.get('/healthz').status_code,'readyz':client.get('/readyz').status_code}
    (HERE/'http-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
