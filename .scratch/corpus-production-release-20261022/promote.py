"""Promote the validated native scope, through the existing publication gate.

Default is a rollback-only rehearsal. --apply commits the same operation.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv()
from plugins.corpus.service import dsn, _I2_ARCHIVE_ROOT
from plugins.corpus.preparation.repository_pg import PgStore
from plugins.corpus.preparation.engine import check_build_publishable, publish_build
from plugins.corpus.retrieval.index_pg import DDL
from plugins.corpus.retrieval.embedding import VectorConfig
from plugins.corpus.retrieval.native import NativeIndex
from plugins.corpus.retrieval.native_live import refresh_on

ROOT = Path.cwd()
HERE = Path(__file__).parent
SEED = ROOT/'data/corpus-native-pilot/20261021/manifest.json'
RELEASE = ROOT/'data/corpus-native-release/20261022'
BACKUP = ROOT/'data/corpus-native-release/20261022-backup'
TARGET = 'postgres'
PILOT = 'vector_pilot_clean7_20261021'

def save(name, value):
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')

def publications(conn):
    return [list(r.values()) if isinstance(r,dict) else list(r) for r in conn.execute(
        'SELECT source_id,active_build_id,generation FROM corpus.corpus_publications ORDER BY source_id')]

def insert_rows(conn, table, rows):
    count = 0
    for original in rows:
        row = dict(original)
        if table == 'corpus_chunks':
            row.pop('search_tsv')  # Recompute using the target's generated-column definition.
        if table == 'corpus_sources':
            # Admission pointer is assigned only inside this release transaction.
            row['current_decision_id'] = None
        names = list(row)
        json_columns={'metadata_snapshot','quality_report','source_ranges','checkpoint','location','mapping'}
        values = [Jsonb(v) if k in json_columns and v is not None else v for k,v in row.items()]
        stmt = sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING').format(
            sql.Identifier('corpus',table),sql.SQL(',').join(map(sql.Identifier,names)),
            sql.SQL(',').join(sql.Placeholder() for _ in names))
        count += conn.execute(stmt,values).rowcount
    return count

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    fields=conninfo_to_dict(dsn());assert fields['dbname']==TARGET
    os.environ.update(CORPUS_TARGET_DB=TARGET,CORPUS_NATIVE_TARGET_DB=TARGET,
                      CORPUS_VECTOR_TARGET_DB=TARGET)
    config=VectorConfig.from_env();seed=NativeIndex(SEED)
    assert seed.manifest['profile']==config.profile
    allow=seed.manifest['source_allowlist'];bids=sorted({c['build_id'] for c in seed.chunks})
    inventory=json.loads((HERE/'inventory.json').read_text())
    expected=inventory['inventory']['production']['publications']
    pilot_dsn=make_conninfo('',**{**fields,'dbname':PILOT})
    rows={}
    with psycopg.connect(pilot_dsn,row_factory=dict_row) as src:
        src.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        assert publications(src)==seed.manifest['publications']
        for table in ('corpus_sources','corpus_review_decisions','corpus_admissions','corpus_source_checkpoints'):
            rows[table]=src.execute(sql.SQL('SELECT * FROM {} WHERE source_id=ANY(%s::text[])').format(sql.Identifier('corpus',table)),(allow,)).fetchall()
        for table in ('corpus_builds','corpus_units','corpus_chunks','corpus_jobs'):
            rows[table]=src.execute(sql.SQL('SELECT * FROM {} WHERE build_id=ANY(%s::text[])').format(sql.Identifier('corpus',table)),(bids,)).fetchall()
        rows['corpus_jobs']=[r for r in rows['corpus_jobs'] if r['stage']!='published']
        assert all(r['state']!='running' for r in rows['corpus_jobs'])
        metadata=src.execute('SELECT * FROM corpus_retrieval.source_metadata WHERE source_id=ANY(%s::text[])',(allow,)).fetchall()
    assert len(rows['corpus_sources'])==23 and len(bids)==23
    # Copy content-addressed archives into the configured production archive root.
    archive=_I2_ARCHIVE_ROOT
    roots=list((ROOT/'data').glob('*/archive'))+[ROOT/'data/corpus/archive', ROOT/'data/corpus_archive']
    archive_results=[]
    for r in rows['corpus_sources']:
        rel=Path(r['archive_path']);assert not rel.is_absolute() and '..' not in rel.parts
        dest=archive/rel
        candidates=[dest]+[base/rel for base in roots]
        original=next((p for p in candidates if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==r['source_id']),None)
        if original is None:raise RuntimeError('archive_missing:'+r['source_id'])
        if dest.exists():assert hashlib.sha256(dest.read_bytes()).hexdigest()==r['source_id']
        elif args.apply:
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
        archive_results.append({'source_id':r['source_id'],'from':str(original),'to':str(dest)})
    if args.apply:
        BACKUP.mkdir(parents=True,exist_ok=True)
        dump=BACKUP/'postgres-before.dump'
        if not dump.exists():
            with dump.open('xb') as f:
                subprocess.run(['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on','pg','pg_dump','-U','postgres','-d',TARGET,'-Fc','--no-owner','--no-privileges'],stdout=f,stderr=subprocess.PIPE,check=True)
        subprocess.run(['docker','exec','-i','pg','pg_restore','--list'],stdin=dump.open('rb'),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
        env_backup=BACKUP/'env-before'
        if not env_backup.exists():shutil.copyfile(ROOT/'.env',env_backup);env_backup.chmod(0o600)
        save('backup.json',{'dump':str(dump),'bytes':dump.stat().st_size,'sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'env_backup':str(env_backup),'archive_files':archive_results})
    with PgStore(dsn(),sandbox_db=TARGET) as store:
        conn=store._conn
        with conn.transaction(force_rollback=not args.apply):
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('native-release-20261022'))")
            assert publications(conn)==expected,'production_publications_changed'
            assert conn.execute("SELECT count(*) FROM corpus.corpus_jobs WHERE state='running'").fetchone()[0]==0
            counts={}
            for table in ('corpus_sources','corpus_review_decisions','corpus_admissions','corpus_builds','corpus_units','corpus_chunks','corpus_jobs','corpus_source_checkpoints'):
                counts[table]=insert_rows(conn,table,rows[table])
            # Source identity conflicts must not silently reuse a different body/build.
            for table,keys in [('corpus_builds',('build_id',)),('corpus_units',('build_id','unit_id')),('corpus_chunks',('build_id','chunk_id'))]:
                with conn.cursor(row_factory=dict_row) as cur:
                    actual=cur.execute(sql.SQL('SELECT * FROM {} WHERE build_id=ANY(%s::text[])').format(sql.Identifier('corpus',table)),(bids,)).fetchall()
                keyed={tuple(r[k] for k in keys):r for r in actual}
                assert all(keyed[tuple(r[k] for k in keys)]==r for r in rows[table]),table+'_immutable_conflict'
            for r in rows['corpus_sources']:
                existing=conn.execute('SELECT format,mime_type,size_bytes,original_names FROM corpus.corpus_sources WHERE source_id=%s',(r['source_id'],)).fetchone()
                assert existing[:3]==(r['format'],r['mime_type'],r['size_bytes'])
                assert sorted(existing[3])==sorted(r['original_names'])
                conn.execute('UPDATE corpus.corpus_sources SET current_decision_id=%s WHERE source_id=%s',(r['current_decision_id'],r['source_id']))
            published=[]
            for bid in bids:
                check_build_publishable(store,bid)
                p=publish_build(store,bid,activated_at=datetime.now(UTC),owner_id='native-production-20261022',operator='User authorized direct production release; executed by Codex')
                published.append({'source_id':p.source_id,'build_id':p.active_build_id,'generation':p.generation})
            conn.execute(DDL)
            conn.execute('INSERT INTO corpus_retrieval.spaces(profile,definition) VALUES(%s,%s) ON CONFLICT DO NOTHING',(config.profile,Jsonb(config.definition())))
            for r in metadata:
                names=list(r)
                conn.execute(sql.SQL('INSERT INTO corpus_retrieval.source_metadata ({}) VALUES ({}) ON CONFLICT DO NOTHING').format(sql.SQL(',').join(map(sql.Identifier,names)),sql.SQL(',').join(sql.Placeholder() for _ in names)),[Jsonb(v) if isinstance(v,dict) else v for v in r.values()])
            imported=0
            for h,entry in seed.vectors.items():
                imported+=conn.execute("INSERT INTO corpus_retrieval.embeddings(profile,input_hash,dimensions,status,embedding) VALUES(%s,%s,%s,'ready',%s::vector) ON CONFLICT DO NOTHING",(config.profile,h,config.dimensions,json.dumps(entry['vector']))).rowcount
            seed.target=TARGET;seed.manifest['target_db']=TARGET
            with conn.cursor() as cur:fresh=refresh_on(cur,seed)
            expected_chunks={(c['build_id'],c['chunk_id']):c for c in seed.chunks}
            actual_chunks={(c['build_id'],c['chunk_id']):c for c in fresh.chunks}
            assert actual_chunks.keys()==expected_chunks.keys()
            compared_fields=('source_id','build_id','chunk_id','kind','title_text','section_path','unit_refs','context_refs','search_text','input_hash')
            differences=[{'key':k,'fields':[f for f in compared_fields if c.get(f)!=actual_chunks[k].get(f)]} for k,c in expected_chunks.items() if any(c.get(f)!=actual_chunks[k].get(f) for f in compared_fields)]
            save('projection-differences.json',differences)
            assert not differences,differences[:2]
            assert all(c['input_hash'] in fresh.vectors for c in fresh.chunks)
            manifest={**seed.manifest,'schema':'native-evidence-release-1','release_id':'native-production-20261022','publications':publications(conn)}
            report={'applied':args.apply,'inserted':counts,'published':published,'native_chunks':len(fresh.chunks),'vectors_imported':imported,'publications':manifest['publications'],'embedding_requests':0}
            if args.apply:
                RELEASE.mkdir(parents=True,exist_ok=True)
                for name in manifest['files']:shutil.copyfile(SEED.parent/name,RELEASE/name)
                (RELEASE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
                NativeIndex(RELEASE/'manifest.json')
        save('promotion.json' if args.apply else 'rehearsal.json',report)
        print(json.dumps(report,ensure_ascii=False,default=str))

if __name__=='__main__':main()
