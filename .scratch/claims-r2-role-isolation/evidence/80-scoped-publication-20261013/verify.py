"""Fresh-process read-only publication verification via Python and registered tool."""
import asyncio
import hashlib
import json
import os
import socket
import sys
from collections import Counter
from pathlib import Path
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[3]
sys.path.insert(0,str(REPO))
from plugins.corpus.structured.query import SemanticQueryPage,query_semantic
from plugins.corpus.structured.snapshot import source_unit_id
from plugins.corpus.structured.store import read_semantic
from plugins.tools.corpus_semantic_query import corpus_semantic_query


def denied(*args,**kwargs):
    raise RuntimeError('verification must not access network')
socket.socket.connect=denied
socket.create_connection=denied
socket.getaddrinfo=denied


def digest(path):return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()


async def main():
    result=json.loads((HERE/'publication-result.json').read_text())
    plan=json.loads((HERE/'release-plan.json').read_text())
    checks=[];counts=Counter()
    for pub in result['publications']:
        root=Path(pub['store_root']); db=root/'index/structured.sqlite3'; before=digest(db)
        view=read_semantic(pub['source_id'],pub['build_id'],store_root=root)
        assert view.manifest.publication_id==pub['publication_id']
        assert view.manifest.quality_status=='review_required'
        expected={rid for row in plan['releases'] if row['snapshot_id']==pub['snapshot_id'] for rid in row['record_ids']}
        records=[];cursor=None
        while True:
            page=query_semantic(pub['source_id'],pub['build_id'],purpose='cite',limit=100,max_chars=1000000,cursor=cursor,store_root=root)
            assert 'CS_PUBLICATION_EXPLICIT_GAPS' in page.error_codes
            records.extend(page.records)
            cursor=page.next_cursor
            if not cursor:break
        assert len(records)==len(expected)==pub['records']
        assert {r.record_id for r in records}==expected
        units={(u.chunk_id.removeprefix('chunk:'),source_unit_id(u)):u for u in view.snapshot.units}
        evidence_count=0
        for record in records:
            counts[record.role]+=1
            assert record.context_status=='complete'
            for proof in record.evidence:
                unit=units[(proof.handle.split('#chunk:')[1],proof.unit_id)]
                assert proof.quote==unit.text[proof.start:proof.end]
                assert proof.text_sha256==unit.text_sha256
                evidence_count+=1
        os.environ['CORPUS_STRUCTURED_ROOT']=str(root)
        tool_checks=[]
        for role in pub['roles']:
            known=next(r for r in records if r.role==role)
            args={'source_id':pub['source_id'],'build_id':pub['build_id'],'purpose':'cite','field_filters':{'record_id':known.record_id},'max_chars':100000}
            body=await corpus_semantic_query.ainvoke(args)
            actual=SemanticQueryPage.model_validate_json(body)
            assert [r.record_id for r in actual.records]==[known.record_id]
            assert 'CS_PUBLICATION_EXPLICIT_GAPS' in actual.error_codes
            tool_checks.append({'role':role,'record_id':known.record_id,'pass':True,'query':args})
        assert digest(db)==before
        checks.append({'publication_id':pub['publication_id'],'snapshot_id':pub['snapshot_id'],'store_root':str(root),'records':len(records),'evidence_ranges_verified':evidence_count,'read_only_index_unchanged':True,'registered_tool_checks':tool_checks,'pass':True})
    assert all(digest(REPO/name)==value for name,value in plan['source_files'].items())
    out={'status':'PASS','cwd':str(Path.cwd()),'model_calls':0,'production_pg_access':0,'source_files_unchanged':True,'counts':dict(counts),'publications':checks,'boundary':'publish + positive_query only; no live delivery/context_use/report_reference'}
    raw=json.dumps(out,ensure_ascii=False,indent=2)+'\n'
    path=HERE/'verification.json'
    if path.exists():assert path.read_text()==raw
    else:path.write_text(raw)
    print(json.dumps({'status':'PASS','publications':len(checks),'counts':dict(counts),'evidence_ranges':sum(c['evidence_ranges_verified'] for c in checks)},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
