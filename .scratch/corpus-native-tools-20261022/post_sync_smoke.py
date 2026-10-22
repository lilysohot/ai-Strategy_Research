"""Small final check after ready-cache import and stricter date-drift guard."""
import asyncio,json,time
from unittest.mock import patch
from verify_tools import prior,native_pg,search_tool,fetch_tool,service,fetch_hit,search_call,save
from plugins.corpus.retrieval.embedding import DoubaoEmbedder

async def main():
    rows=[]
    with patch.object(native_pg,'query_vector',side_effect=prior.vector),patch.object(DoubaoEmbedder,'embed',side_effect=AssertionError('No provider calls')),patch.object(search_tool,'get_service',return_value=service),patch.object(fetch_tool,'get_service',return_value=service):
        for q in [prior.queries[0],prior.queries[15],prior.queries[-1]]:
            start=time.monotonic();payload=json.loads(await search_call(q['question']))
            assert payload['ok'] and payload['coverage']['retrieval_mode']=='hybrid'
            chars=0
            for h in payload['hits']:
                texts,pages=await fetch_hit(h)
                chars+=sum(map(len,texts.values()))
            assert chars<=16000
            rows.append({'id':q['id'],'mode':'hybrid','raw_chars':chars,'elapsed_ms':round((time.monotonic()-start)*1000)})
    save('post-sync-smoke.json',rows)
    print(rows)
if __name__=='__main__':asyncio.run(main())
