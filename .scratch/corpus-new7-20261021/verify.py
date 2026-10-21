"""Check actual published versions, source hashes, search and verbatim fetch."""
from run_batch import *
from plugins.corpus.service import CorpusService
from plugins.corpus.preparation import read_pg
from plugins.corpus.preparation.contract import JobStage, JobState
from plugins.corpus.retrieval.embedding import VectorConfig
from plugins.corpus.retrieval.index_pg import VectorIndex
from dataclasses import replace

parser=argparse.ArgumentParser(); parser.add_argument('--hybrid',action='store_true')
args=parser.parse_args()
rows=[r for r in load('build-results.json') if r['outcome']=='published']
rows += [r for r in load('ocr-build-results.json') if r['outcome']=='published']
assert len(rows)==7
queries={'a981b064':'中泰 双锚 定价 贵州茅台', 'b505dcd7':'DS V4.1 Flash 国产卡 10T',
         '8b11fbdd':'FCC 光模块 规则', 'eecaab99':'DeepSeek V4.1 Flash 1017',
         'cb2648e1':'OCP NPO 铜缆', '17aa814c':'Kweichow Moutai Feitian',
         '8877abc5':'长江 消费 养殖 乳品'}
os.environ['CORPUS_RETRIEVAL_MODE']='hybrid' if args.hybrid else 'lexical'
os.environ['CORPUS_RETRIEVAL_RANKING']='body-constraints-v1' if args.hybrid else 'off'
os.environ['CORPUS_RETRIEVAL_RANKING_TARGET_DB']=TARGET
service=CorpusService(TARGET_DSN)
checks=[]
with PgStore(TARGET_DSN,sandbox_db=TARGET) as store:
    for row in rows:
        build=store.get_build(row['build_id']); pub=store.get_publication(row['source_id'])
        assert pub.active_build_id==build.build_id
        check_build_publishable(store,build.build_id)
        job=store.get_job(build.build_id,JobStage.PUBLISHED)
        assert job.state is JobState.SUCCEEDED
        source=store.get_source(row['source_id'])
        assert hashlib.sha256((ARCHIVE/source.archive_path).read_bytes()).hexdigest()==row['source_id']
        query=queries[row['source_id'][:8]]
        hits,coverage=service.search_with_coverage(query,limit=20)
        save(('hybrid-' if args.hybrid else 'lexical-')+row['source_id'][:8]+'.json',
             {'query':query,'hits':[asdict(h) for h in hits],'coverage':coverage})
        if args.hybrid:
            assert coverage['retrieval']['used']=='hybrid',coverage['retrieval']
            assert coverage['retrieval']['vector_candidates']>0
        assert any(h.doc_id==read_pg.build_handle(build.build_id) for h in hits),(row['original_name'],'not found')
        verified=0
        for chunk in store.get_chunks(build.build_id):
            evidence=service.fetch_verbatim(read_pg.build_handle(build.build_id),'chunk:'+chunk.chunk_id)
            assert evidence.active and evidence.source_id==row['source_id']
            for unit in evidence.units:
                original=store.get_unit(build.build_id,unit.unit_id)
                assert original.raw_text==unit.raw_text
            verified+=1
        checks.append({'source_id':row['source_id'],'build_id':build.build_id,
                       'query':query,'search_found':True,'verified_chunks':verified,
                       'coverage':coverage,
                       'publication_record':json.loads(job.checkpoint),
                       'gaps':[g.as_payload() for g in gap_records_of(build,store=store)]})
        print(json.dumps({'source':row['source_id'][:8],'verified_chunks':verified}),flush=True)
    for original in load('inventory.json'):
        source=store.get_source(original['source_id'])
        assert hashlib.sha256((ARCHIVE/source.archive_path).read_bytes()).hexdigest()==original['source_id']
    for provenance in load('ocr-provenance.json'):
        checkpoint=store.get_source_checkpoint(provenance['derived_source_id'],'local-ocr-provenance-1')
        assert json.loads(checkpoint)==provenance
before=load('before.json')
after={db:publications(db) for db in before}
for db in ('postgres','vector_pilot_corpus_20261020'): assert before[db]==after[db]
assert all(row in after[TARGET] for row in before[TARGET])
save('after-final.json',after)
with psycopg.connect(TARGET_DSN) as conn:
    running=conn.execute("SELECT count(*) FROM corpus.corpus_jobs WHERE state='running'").fetchone()[0]
assert running==0
index=VectorIndex(TARGET_DSN,replace(VectorConfig.from_env(),target_db=TARGET))
status=index.status()
save('verification-hybrid.json' if args.hybrid else 'verification.json',
     {'sources':checks,'running_jobs':running,'production_and_old_pilot_unchanged':True,'vector_status':status})
