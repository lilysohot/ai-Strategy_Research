"""Real tools, real PG, cached query vectors: full 57 plus fallback/off checks."""
import asyncio,importlib,importlib.util,json,os,sys,shutil,time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('prior_api',ROOT/'.scratch/corpus-native-integration-20261021/verify_api.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
from plugins.corpus.retrieval import native_live,native_pg
from plugins.corpus.retrieval import hybrid
from plugins.corpus.retrieval.embedding import DoubaoEmbedder,EmbeddingError
from plugins.corpus.retrieval.native import NativeBlock,NativeSpan,NativeIndex
from plugins.corpus.retrieval.diagnostics import RetrievalTrace
from plugins.corpus.service import CorpusService
search_tool=importlib.import_module('plugins.tools.corpus_search')
fetch_tool=importlib.import_module('plugins.tools.corpus_fetch')
async def search_call(query,**kwargs):return await search_tool.corpus_search.ainvoke({'query':query,**kwargs})
async def fetch_call(**kwargs):return await fetch_tool.corpus_fetch.ainvoke(kwargs)
OUT=ROOT/'data/corpus-native-pilot/20261021'
OUT.mkdir(parents=True,exist_ok=True)
for p in (prior.HERE/'index').iterdir():
    if p.is_file():
        dest=OUT/p.name
        if dest.exists():assert dest.read_bytes()==p.read_bytes()
        else:shutil.copyfile(p,dest)
os.environ.update(CORPUS_NATIVE_RETRIEVAL='pilot',CORPUS_NATIVE_TARGET_DB=prior.batch.TARGET,
                  CORPUS_NATIVE_INDEX=str(OUT/'manifest.json'))
service=CorpusService(prior.batch.TARGET_DSN)
def save(name,data):(HERE/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def read(path):return json.loads(path.read_text())
def enabled(value):os.environ['CORPUS_NATIVE_RETRIEVAL']=value

async def fetch_hit(hit,budget=6000):
    pages=[];texts={};raw_maps={}
    response=await fetch_call(doc_id=hit['doc_id'],locators=hit['context_locators'],view='compact',max_chars=budget)
    for _ in range(100):
        page=json.loads(response);assert page['ok'],page
        assert len(response)<=budget
        pages.append(page)
        for item in page['items']:
            loc=item['locator'];fragment=item.get('fragment');start=fragment['start'] if fragment else 0
            assert len(texts.get(loc,''))==start
            texts[loc]=texts.get(loc,'')+item['text']
            raw_maps.setdefault(loc,[]).extend(item.get('native_slices',[]))
            for s in item.get('native_slices',[]):
                u=prior.index.units.get((hit['build_id'],s['unit_id']))
                if u:
                    assert item['text'][s['text_start']:s['text_end']]==u['raw_text'][s['start']:s['end']]
        if page['exhausted']:
            assert page['fetch_complete'] and not page['unresolved'];break
        response=await fetch_call(doc_id=hit['doc_id'],cursor=page['next_cursor'],max_chars=budget)
    else:raise AssertionError('paging did not complete')
    return texts,pages

async def main():
    seed=NativeIndex(OUT/'manifest.json')
    fresh=native_live.refresh(prior.batch.TARGET_DSN,prior.batch.TARGET,seed)
    old={(c['build_id'],c['chunk_id']):c for c in seed.chunks}
    new={(c['build_id'],c['chunk_id']):c for c in fresh.chunks}
    assert old.keys()==new.keys(),(len(old),len(new))
    assert all(old[k]['search_text']==new[k]['search_text'] and old[k]['unit_refs']==new[k]['unit_refs'] for k in old)
    assert len(new)==585
    results=[];cases=[];original={r['id']:r for r in read(prior.HERE/'results.json')}
    with patch.object(native_pg,'query_vector',side_effect=prior.vector),patch.object(hybrid,'query_vector',side_effect=prior.vector),patch.object(DoubaoEmbedder,'embed',side_effect=AssertionError('No model calls')),patch.object(search_tool,'get_service',return_value=service),patch.object(fetch_tool,'get_service',return_value=service):
        for q in prior.queries:
            start=time.monotonic()
            body=await search_call(q['question']) # Actual default limit=10.
            compact=search_tool.fit_search_payload(body,12000)
            payload=json.loads(compact);assert payload['ok'] and not payload.get('hits_elided'),payload
            assert len(payload['hits'])<=10
            delivered=[];pages=[]
            for hit in payload['hits']:
                texts,part=await fetch_hit(hit);pages.extend(part)
                for loc,text in texts.items():
                    cid=native_live.unquote(loc[len(native_live.PREFIX):].rsplit('/',1)[0])
                    expected=next(b for b in original[q['id']]['result']['blocks'] if b['build_id']==hit['build_id'] and b['chunk_id']==cid)
                    assert text==expected['text']
                    delivered.append(NativeBlock(hit['source_id'],hit['build_id'],cid,hit['published'],text,tuple(NativeSpan(**s) for s in expected['slices'])))
            assert {(b.build_id,b.chunk_id) for b in delivered}=={(b['build_id'],b['chunk_id']) for b in original[q['id']]['result']['blocks']}
            score=prior.actual_score(prior.scorer.questions[q['id']],delivered)
            baseline=prior.baseline[q['id']]['methods']['hybrid_bands']['groups']
            lost=[g for g,v in baseline.items() if v and not score['groups'][g]]
            assert not lost,(q['id'],lost)
            compact=search_tool.fit_search_payload(body,12000)
            fit=json.loads(compact);assert fit['ok'],fit
            cases.append({'id':q['id'],'hits':len(payload['hits']),'blocks':len(delivered),'body_characters':sum(len(b.text) for b in delivered),'score':score,'lost_groups':lost,'search_json_chars':len(body),'hits_elided_at_12000':fit.get('hits_elided',0),'fetch_pages':len(pages),'elapsed_ms':round((time.monotonic()-start)*1000)})
            results.append({'id':q['id'],'search':payload,'fetch_pages':pages})
            save('cases.json',cases);save('results.json',results)
            print(q['id'],cases[-1],flush=True)
            if '--smoke' in sys.argv:break
        # Turning off routes back to the exact existing service path, while native handles survive.
        enabled('off');off_cases=[]
        for qrow in prior.queries:
            q=qrow['question']
            old_hits,old_cov=service.search_with_coverage(q)
            off=json.loads(await search_call(q))
            assert [(h['doc_id'],h['locator']) for h in off['hits']]==[(h.doc_id,h.locator) for h in old_hits]
            assert 'native' not in off['coverage'] and all(not h['locator'].startswith(native_live.PREFIX) for h in off['hits'])
            off_cases.append({'id':qrow['id'],'matched_legacy_service':True,'hits':len(off['hits'])})
        save('off-cases.json',off_cases)
        q=prior.queries[0]['question']
        first=results[0]['search']['hits'][0]
        await fetch_hit({**first,'context_locators':first['context_locators'][:1]},3000)
        enabled('pilot')
        with patch.object(native_pg,'query_vector',side_effect=EmbeddingError('test_unavailable')):
            fallback=json.loads(await search_call(q))
            assert fallback['ok'] and fallback['coverage']['retrieval_mode']=='lexical'
            assert fallback['coverage']['fallback_reason']=='embedding_test_unavailable'
            for h in fallback['hits']:await fetch_hit(h)
        save('fallback.json',fallback)
    save('audit.json',{'queries':len(cases),'native_projection_matches_frozen585':True,'new_embedding_calls':0,
        'default_tool_limit':10,'all_selected_blocks_delivered':True,'raw_pages_verified':True,
        'regressions':[],'off_restores_existing_service':True,'native_handles_work_when_off':True,
        'embedding_failure_scoped_lexical_fallback':True,'publications_unchanged':prior.batch.publications(prior.batch.TARGET)==prior.index.manifest['publications'],
        'search_budget_elisions':[c['id'] for c in cases if c['hits_elided_at_12000']]})

if __name__=='__main__':asyncio.run(main())
