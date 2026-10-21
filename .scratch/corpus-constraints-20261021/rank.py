"""Pure candidate replay through real selector; freeze rankings before scoring labels."""
import sys,json,hashlib,time
from pathlib import Path
from dataclasses import asdict
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
PRIOR=ROOT/'.scratch/corpus-clean7-rebuild-20261021'
sys.path.insert(0,str(ROOT))
from signals import Signals,rerank_pool,final_rank,prior,guarded_year_order
from plugins.corpus.preparation.search_pg import SearchHit
from plugins.corpus.retrieval.diagnostics import RetrievalTrace,candidate_fates
from plugins.corpus.preparation.selection import SelectedBand
from plugins.corpus.retrieval.dedup import dedupe_contained_hits
from plugins.corpus.service import CorpusService

def read(p): return json.loads(p.read_text())
def save(name,obj): (HERE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2))
def restore(rows):
    fields=('section_path','unit_refs','cells','label_path','context_chunk_ids')
    return tuple(SearchHit(**{**r,**{k:tuple(tuple(x) if isinstance(x,list) else x for x in r[k]) for k in fields}}) for r in rows)
def scope(hits): return {(h.build_id,c) for h in hits for c in (h.context_chunk_ids or (h.chunk_id,))}
def restore_trace(data):
    t=RetrievalTrace()
    for key in ('lexical','dense','fused','selected'): setattr(t,key,restore(data[key]))
    t.chunk_order={k:tuple(v) for k,v in data['chunk_order'].items()}
    t.selectable_bands=tuple(SelectedBand(**{**r,'pool':tuple(r['pool'])}) for r in data['selectable_bands'])
    t.source_limit=data['source_limit'];t.status=data['status']
    return t

def main():
    prepared=read(HERE/'prepared.json')
    authority=read(PRIOR/'new-authority.json')
    signal=Signals(read(PRIOR/'new-corpus.json'),authority,prepared['metadata'])
    structures={s:{c:SimpleNamespace(**{**v,'units':tuple(SimpleNamespace(**u) for u in v['units'])}) for c,v in rows.items()} for s,rows in read(HERE/'structures.json').items()}
    service=CorpusService.__new__(CorpusService)
    out={}
    timings=[]
    for q in prepared['queries']:
        trace=restore_trace(read(PRIOR/f'retrieval/{q["id"]}-new-hybrid.json')['trace'])
        started=time.perf_counter()
        intent=signal.intent(q['question'],q['lexemes'])
        features={h.chunk_id:signal.feature(h,intent) for h in trace.fused}
        def select(fused,lexical):
            t=RetrievalTrace(fused=fused,lexical=lexical,dense=trace.dense,chunk_order=trace.chunk_order,status='hybrid')
            selected=service._selected_context_hits(fused,trace.chunk_order,10,lexical_fallback_hits=lexical,trace=t)
            selected=service._attach_table_header_context(selected,trace.chunk_order,structures)
            t.selected=dedupe_contained_hits(selected)
            return t
        base=select(trace.fused,trace.lexical)
        assert base.selected==trace.selected,q['id']
        methods={'baseline':base}
        old_signal=prior.Signals(read(PRIOR/'new-corpus.json'),authority,prepared['metadata'])
        old_intent=old_signal.intent(q['question'],q['lexemes'])
        old_features={h.chunk_id:old_signal.feature(h,old_intent) for h in trace.fused}
        old=select(rerank_pool(trace.fused,old_features,'entity'),rerank_pool(trace.lexical,old_features,'entity'))
        old.selected=tuple(sorted(old.selected,key=lambda h:-old_features[h.chunk_id]['source_hint']))
        methods['previous']=old
        for name in ('aliases_roles','years','guarded'):
            t=select(rerank_pool(trace.fused,features,'entity'),rerank_pool(trace.lexical,features,'entity'))
            t.selected=tuple(sorted(t.selected,key=lambda h:-features[h.chunk_id]['source_hint']))
            if name=='years':
                # Preserve every source's existing output slots. A matching year
                # in an unrelated report must not promote that report globally.
                buckets={sid:iter(sorted([h for h in t.selected if h.source_id==sid],
                    key=lambda h:-features[h.chunk_id]['constraints']['year_fraction']))
                    for sid in {h.source_id for h in t.selected}}
                t.selected=tuple(next(buckets[h.source_id]) for h in t.selected)
            if name=='guarded':
                t.selected=guarded_year_order(t.selected,features,intent)
            methods[name]=t
        no_support=bool(intent['entities']) and not any(f['entity'] for f in features.values())
        timings.append((time.perf_counter()-started)*1000)
        out[q['id']]={'question':q['question'],'intent':intent,'entity_no_candidate_support':no_support,'features':features,
            'methods':{name:{'selected':[asdict(h) for h in t.selected],'fates':candidate_fates(t),'bands':[asdict(b) for b in t.selectable_bands]} for name,t in methods.items()}}
        print(q['id'],intent['entities'],intent['issuers'],len(intent['weights']),'unsupported',no_support)
    save('aliases.json',[asdict(a) for a in signal.aliases])
    save('rankings.json',{'signal_sha256':hashlib.sha256((HERE/'signals.py').read_bytes()).hexdigest(),'prepared_sha256':hashlib.sha256((HERE/'prepared.json').read_bytes()).hexdigest(),
       'methods_note':'previous=prior entity/source scheme; aliases_roles=new constraints without temporal ranking; years=also prefer literal requested years in selected body; no filters',
       'cases':out,'offline_all_variants_ms':timings})

if __name__=='__main__': main()
