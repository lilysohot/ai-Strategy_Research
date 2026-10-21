"""User-authorized seven-source batch, bounded to the existing hybrid pilot DB."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from plugins.corpus.service import dsn
from plugins.corpus.preparation.admission import load_admission_policy
from plugins.corpus.preparation.contract import (
    MaterialType, ResearchDomain, ReviewDecision, ReviewedDecision, canonical_fingerprint,
)
from plugins.corpus.preparation.engine import (
    PlanEntry, plan_builds, execute_builds, DEFAULT_LEASE, gap_records_of,
    check_build_publishable, publish_build,
)
from plugins.corpus.preparation.gaps import blocking_gaps
from plugins.corpus.preparation.repository_pg import PgStore
from plugins.corpus.preparation.text_publication import TextPublication

TARGET = 'vector_pilot_clean7_20261021'
ARCHIVE = ROOT/'data/vector-pilot-clean7-20261021/archive'
BASE = conninfo_to_dict(dsn())
TARGET_DSN = make_conninfo(**{**BASE, 'dbname': TARGET})
os.environ.update(CORPUS_TARGET_DB=TARGET, CORPUS_DSN=TARGET_DSN,
                  CORPUS_VECTOR_TARGET_DB=TARGET, CORPUS_READ_CHAIN='new')

def save(name, value):
    path=HERE/name
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    tmp.replace(path)

def load(name):
    return json.loads((HERE/name).read_text())

def publications(database):
    with psycopg.connect(make_conninfo(**{**BASE, 'dbname': database})) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        assert conn.execute('SELECT current_database()').fetchone()[0] == database
        return [list(r) for r in conn.execute(
            'SELECT source_id,active_build_id,generation FROM corpus.corpus_publications ORDER BY source_id'
        ).fetchall()]

def prepare():
    if (HERE/'manifest.json').exists():
        print('Manifest already frozen; reusing.'); return
    inventory=load('inventory.json')
    sources=[]
    for row in inventory:
        assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['source_id']
        is_subscription = any(s in row['name'] for s in ('FundaAI', '_研究'))
        sources.append({
            'path':row['path'], 'original_name':row['name'], 'source_id':row['source_id'],
            'domain_hint':'company' if '贵州茅台' in row['name'] else 'industry',
            'material_type':'personal_or_external_subscription' if is_subscription else 'research_report',
            'has_usable_text':sum(row['page_text_chars']) >= 200,
            'review_decision_ids':['new7-user-20261021-'+row['source_id']],
        })
    now=datetime.now(UTC).isoformat()
    save('authorization.json', {'recorded_at':now, 'operator':'codex',
        'user_requests':['先发布新增的7份吧。也把整个发布的操作执行详细说明',
                         '历史预检均有图片或表格提取缺口…不能成为阻碍发布的条件',
                         '个人／外部订阅类 PDF 也可以用呀'],
        'scope':'Seven listed files only; available text with explicit missing visual coverage. '
                'No claim of human visual completeness review.', 'target_db':TARGET})
    save('policy.json', {'policy_rev':'v3-dev-20261021','frozen':True,
        'scope':'dev','auto_decision':{'enabled':False},
        'allowed_materials':['research_report','personal_or_external_subscription'],
        'dev_lane':{'lane_id':'new7-user-20261021','sources':[{'source_id':s['source_id']} for s in sources]}})
    before={database:publications(database) for database in
            (TARGET,'vector_pilot_corpus_20261020','postgres')}
    save('before.json',before)
    backup=ROOT/'data/vector-pilot-clean7-20261021/pre-new7-20261021.dump'
    if backup.exists(): raise RuntimeError('Backup path already exists; inspect before reuse')
    with backup.open('xb') as output:
        subprocess.run(['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on',
                        'pg','pg_dump','-U','postgres','-d',TARGET,'-Fc','--no-owner','--no-privileges'],
                       stdout=output,stderr=subprocess.PIPE,check=True)
    save('backup.json',{'path':str(backup),'bytes':backup.stat().st_size,
                        'sha256':hashlib.sha256(backup.read_bytes()).hexdigest()})
    save('manifest.json',{'target_db':TARGET,'archive_root':str(ARCHIVE),'sources':sources})
    print(json.dumps({'phase':'prepared','sources':len(sources),'text_sources':sum(s['has_usable_text'] for s in sources)}))

def build():
    manifest=load('manifest.json'); policy=load_admission_policy(HERE/'policy.json',allow_dev_lane=True)
    auth=load('authorization.json'); now=datetime.fromisoformat(auth['recorded_at'])
    results=load('build-results.json') if (HERE/'build-results.json').exists() else []
    with PgStore(TARGET_DSN,sandbox_db=TARGET) as store:
        for row in manifest['sources']:
            if any(r['source_id']==row['source_id'] for r in results): continue
            if not row['has_usable_text']:
                results.append({**row,'outcome':'awaiting_ocr_or_readable_source'})
                save('build-results.json',results); continue
            assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['source_id']
            store.put_reviewed_decision(ReviewedDecision(
                row['review_decision_ids'][0],row['source_id'],
                'U: explicit current conversation authorization; recorded by Codex',now,
                ReviewDecision.ADMITTED,
                'User requested publication of these seven supplied files and explicitly allowed '
                'subscription research and incomplete visual coverage; see '+str(HERE/'authorization.json')+
                '. Material/domain classification by Codex; not a human completeness review.',
                material_type=MaterialType(row['material_type']),research_domain=ResearchDomain(row['domain_hint'])))
            entry=PlanEntry(path=row['path'],original_name=row['original_name'],
                            domain_hint=ResearchDomain(row['domain_hint']),
                            review_decision_ids=tuple(row['review_decision_ids']))
            plan=plan_builds([entry],policy=policy)
            outcome=execute_builds(store,plan,policy=policy,archive_root=ARCHIVE,
                                   owner_id='new7-publisher',now=datetime.now(UTC),lease=DEFAULT_LEASE).outcomes[0]
            record={**row,'outcome':'built' if outcome.build else 'not_in_scope',
                    'admission':outcome.admission.decision.value,
                    'units':outcome.unit_count,'chunks':outcome.chunk_count}
            if outcome.build:
                record.update(build_id=outcome.build.build_id,quality_report=json.loads(outcome.build.quality_report),
                              gaps=[r.as_payload() for r in gap_records_of(outcome.build,store=store)])
            results.append(record); save('build-results.json',results)
            print(json.dumps({k:v for k,v in record.items() if k not in ('gaps','quality_report')},ensure_ascii=False),flush=True)

def retry_oversized():
    results=load('build-results.json')
    retry=[r for r in results if r.get('quality_report',{}).get('oversized_chunks') and r['outcome']!='published']
    if not retry: return
    save('oversized-build-history.json',retry)
    save('build-results.json',[r for r in results if r not in retry])
    build()

def archive_pending():
    from plugins.corpus.preparation.source import ingest_source
    archived=[]
    with PgStore(TARGET_DSN,sandbox_db=TARGET) as store:
        for row in load('manifest.json')['sources']:
            if row['has_usable_text']: continue
            outcome=ingest_source(store,row['path'],ARCHIVE,original_name=row['original_name'])
            assert outcome.registered
            assert outcome.source.source_id==row['source_id']
            archived.append(asdict(outcome))
    save('pending-archives.json',archived)

def publish():
    results=load('build-results.json'); auth=load('authorization.json')
    with PgStore(TARGET_DSN,sandbox_db=TARGET) as store:
        for row in results:
            if not row.get('build_id'): continue
            build=store.get_build(row['build_id'])
            gaps=blocking_gaps(gap_records_of(build))
            if gaps:
                acceptance=TextPublication(build.source_id,build.build_id,canonical_fingerprint(asdict(build)),
                    'codex:user-authorized-new7',auth['recorded_at'],str(HERE/'authorization.json'),
                    tuple(r.key for r in gaps))
                store.put_text_publication(acceptance)
                row['text_publication_id']=acceptance.acceptance_id
            check_build_publishable(store,build.build_id)
            publication=publish_build(store,build.build_id,activated_at=datetime.now(UTC),
                owner_id='new7-publisher',operator='codex:user-authorized-new7')
            row.update(outcome='published',generation=publication.generation,
                       gaps=[r.as_payload() for r in gap_records_of(build,store=store)])
            save('build-results.json',results)
            print(json.dumps({'name':row['original_name'],'outcome':row['outcome'],'chunks':row['chunks'],
                              'gap_count':len(row['gaps'])},ensure_ascii=False),flush=True)
    before=load('before.json')
    after={db:publications(db) for db in before}
    for db in ('postgres','vector_pilot_corpus_20261020'):
        assert before[db]==after[db], f'Unexpected publication change: {db}'
    previous={r[0]:r for r in before[TARGET]}
    assert all(previous[sid]==r for r in after[TARGET] if (sid:=r[0]) in previous)
    save('after.json',after)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('phase',choices=('prepare','build','publish','retry_oversized','archive_pending'))
    globals()[parser.parse_args().phase]()
