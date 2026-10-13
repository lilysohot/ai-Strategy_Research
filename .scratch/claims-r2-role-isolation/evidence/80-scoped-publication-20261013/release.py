"""Prepare and publish signed selections without model calls or source-store writes."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import socket
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from plugins.corpus.structured.ledger import _read_object, _reader, _writer
from plugins.corpus.structured.store import ArtifactReference, _load_candidate, publish_semantic, read_semantic
from plugins.corpus.structured.query import query_semantic

BASE = REPO / '.scratch/claims-r2-role-isolation'
E = BASE / 'evidence'
HERE = Path(__file__).resolve().parent
DEST = REPO / '.local/claims-r2-publication-20261013'


def denied(*args, **kwargs):
    raise RuntimeError('release is zero-network and zero-model')

socket.socket.connect = denied
socket.create_connection = denied
socket.getaddrinfo = denied


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, value):
    raw = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        assert path.read_text() == raw, f'write-once collision: {path}'
    else:
        path.write_text(raw)


def prepare():
    worksheet = BASE / 'adjudication/worksheet.json'
    claims_path = E/'17-structured-extraction-convergence-closure-20261009/p1r5-claims-adjudication-v2/candidate-adjudications.signed.json'
    gate_path = E/'77-gate33-rescore-under-v3-20261013/r1-score/gate33-score-under-v3.json'
    assert load(gate_path)['verdict'] == 'PASS'
    claims = load(claims_path)
    assert claims['human_gate_satisfied'] and claims['quality_gate_passed']
    inputs = [worksheet, claims_path, gate_path]
    decisions = {r['candidate_id']: r for r in load(worksheet)['records']}
    claims_decisions = {r['candidate_id']:r for r in claims['adjudications']}
    roots = []
    for slug in ['industrial-fulian-md', 'optical-module-docx']:
        roots.append((E/'32-items-v6-reasoning-refreeze-20261011/live/treatment-store'/slug, 'items'))
    for name in ['replay-claims-industrial-fulian', 'replay-claims-optical-module', 'live-claims-optical-routing-delta']:
        roots.append((E/'17-structured-extraction-convergence-closure-20261009/p1r5-claims-replay-freeze'/name/'replay-store', 'claims'))
    rerun_data = {}
    for prefix, sub in [('65-rerun-two-arm-protocol-20261013','r6-assembly'), ('66-base-protocol-change-proposal-20261013','r4-assembly')]:
        path = E/prefix/sub/'assembled-scoring-input.json'; inputs.append(path)
        assembly=load(path)
        assert all(r['reviewer']=='xyl' for r in assembly['audit'])
        rows = {r['candidate_id']:r for r in assembly['raw']}
        rerun_data[prefix[:2]] = [(r, dict(rows[r['candidate_id']]['semantic_fields'])) for r in assembly['mappings'] if r['judgement'] in {'matched','correct_extra'}]
    # Bind signed raw rerun candidates only to exact proposition + semantic fields
    # in the official retained payload. Split/rewritten outputs remain excluded.
    for name in ['NT-I06', 'NT-I41']:
        roots.append((E/'65-rerun-two-arm-protocol-20261013/r3-control-live'/name/'store', '65'))
    roots.append((E/'66-base-protocol-change-proposal-20261013/r2-publish/store-run4-final', '66'))
    releases=[]; exclusions=[]; mappings=[]; all_files={}
    for root, kind in roots:
        root=root.resolve()
        db=root/'index/structured.sqlite3'
        all_files[str(db.relative_to(REPO))]=sha(db)
        connection=_reader(root)
        for row in connection.execute('SELECT * FROM tasks WHERE artifact_sha256 IS NOT NULL'):
            if row['role'] not in {'claims','material_items'}:continue
            ref=ArtifactReference(batch_id=row['batch_id'],task_id=row['task_id'],artifact_sha256=row['artifact_sha256'])
            payload=_read_object(root,row['payload_object_sha256'])
            plan=json.loads(connection.execute('SELECT plan_json FROM batches WHERE batch_id=?',(row['batch_id'],)).fetchone()[0])
            records=payload['facts'] if kind=='claims' else payload['understanding']['items']
            wanted=[]
            for record in records:
                rid=record['fact_id'] if kind=='claims' else record['item_id']
                decision=None
                if kind in {'claims','items'}:
                    decision=(claims_decisions if kind=='claims' else decisions).get(rid)
                    if decision and decision.get('reviewer')!='xyl':raise ValueError('unsigned decision')
                    if decision and kind=='claims':assert decision['original_candidate']==record
                    if decision and kind=='items':
                        original=decision['original_candidate']
                        assert original['text']==record['text'] and original['speaker_ref']==record['speaker_ref']
                else:
                    matches=[]
                    for d, fields in rerun_data[kind]:
                        if fields['proposition']!=record['text']:continue
                        if any(fields.get(k)!=record[k] for k in ['semantic_type','statement_role','polarity']):continue
                        matches.append(d)
                    if len(matches)==1:decision=matches[0]
                if not decision or decision['judgement'] not in {'matched','correct_extra'}:
                    exclusions.append({'artifact':ref.artifact_sha256,'record_id':rid,'reason':decision['judgement'] if decision else 'no_exact_signed_candidate_binding'})
                    continue
                try:
                    _load_candidate(connection,root,ref,(rid,))
                except Exception as exc:
                    exclusions.append({'artifact':ref.artifact_sha256,'record_id':rid,'reason':str(exc)})
                    continue
                wanted.append(rid)
                mappings.append({'record_id':rid,'candidate_id':decision['candidate_id'],'judgement':decision['judgement'],'kind':kind})
            if wanted:
                releases.append({'root':str(root.relative_to(REPO)), 'reference':ref.model_dump(), 'source_id':plan['snapshot']['source_id'],'build_id':plan['snapshot']['build_id'],'snapshot_id':plan['snapshot']['snapshot_id'],'record_ids':sorted(wanted),'role':row['role']})
        connection.close()
        for path in (root/'objects').rglob('*.json'):
            all_files[str(path.relative_to(REPO))]=sha(path)
    result={'authorization':{'basis':'user_chat_2026-10-13: 那么按任务帮我完成发布','publication':True,'zero_call_positive_query':True,'new_model_calls':False,'production_pg':False},'store_root':str(DEST),'inputs':{str(p.relative_to(REPO)):sha(p) for p in inputs},'source_files':all_files,'releases':releases,'record_bindings':mappings,'excluded_records':exclusions,'selected_counts':dict(Counter(r['role'] for r in releases)),'selected_records_by_role':{role:sum(len(r['record_ids']) for r in releases if r['role']==role) for role in ['claims','material_items']},'model_calls':0}
    write_once(HERE/'release-plan.json',result)
    print(json.dumps({k:result[k] for k in ['selected_records_by_role','selected_counts']},ensure_ascii=False))
    print('excluded reasons',Counter(r['reason'] for r in exclusions))
    return result


def publish(plan):
    for name,digest in {**plan['inputs'],**plan['source_files']}.items():assert sha(REPO/name)==digest,name
    groups=defaultdict(list)
    for r in plan['releases']:groups[(r['source_id'],r['build_id'],r['snapshot_id'])].append(r)
    published=[]
    for (sid,bid,snapshot),rows in groups.items():
        target_root=DEST/'stores'/snapshot.removeprefix('sha256:')
        target_root.mkdir(parents=True,exist_ok=True)
        destination=_writer(target_root)
        if destination.execute('SELECT count(*) FROM batches').fetchone()[0]:
            raise RuntimeError('destination already populated; verify instead of replaying')
        # A build has different independently frozen scoped snapshots. Each gets
        # an explicit root; none overwrites another snapshot's publication head.
        for root in sorted({r['root'] for r in rows}):
            src=REPO/root
            source=_reader(src)
            for p in (src/'objects').rglob('*.json'):
                target=target_root/p.relative_to(src);target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():assert target.read_bytes()==p.read_bytes()
                else:shutil.copyfile(p,target)
            destination.execute('BEGIN IMMEDIATE')
            try:
                for table in ['batches','tasks','attempts','derivations']:
                    columns=[r[1] for r in source.execute(f'PRAGMA table_info({table})')]
                    names=','.join(columns); marks=','.join('?' for _ in columns)
                    for row in source.execute(f'SELECT {names} FROM {table}'):
                        destination.execute(f'INSERT INTO {table} ({names}) VALUES ({marks})',tuple(row))
                destination.execute('COMMIT')
            except BaseException:
                destination.execute('ROLLBACK');raise
            source.close()
        destination.close()
        refs=[ArtifactReference.model_validate(r['reference']) for r in rows]
        selection={r['reference']['artifact_sha256']:r['record_ids'] for r in rows}
        pub=publish_semantic(source_id=sid,build_id=bid,snapshot_id=snapshot,artifacts=refs,expected_parent_publication_id=None,store_root=target_root,record_selection=selection,reason_codes=('SELECTED_SIGNED_DEVELOPMENT_SCOPE','NOT_EXHAUSTIVE_DOCUMENT_COVERAGE'))
        published.append({'source_id':sid,'build_id':bid,'snapshot_id':snapshot,'store_root':str(target_root),'publication_id':pub.publication_id,'records':sum(len(r['record_ids']) for r in rows),'roles':sorted({r['role'] for r in rows})})
    result={'publications':published,'store_root':str(DEST),'model_calls':0,'production_pg_access':0,'source_hashes_unchanged':all(sha(REPO/n)==v for n,v in plan['source_files'].items()),'release_plan_sha256':sha(HERE/'release-plan.json')}
    assert result['source_hashes_unchanged']
    write_once(HERE/'publication-result.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    if args.publish:publish(load(HERE/'release-plan.json'))
    else:prepare()
