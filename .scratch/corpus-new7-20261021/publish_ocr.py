"""Publish two explicitly identified OCR derivatives, preserving original parents."""
from run_batch import *
from plugins.corpus.preparation.readers import read_document

records=load('ocr-provenance.json')
assert len(records)==2
policy_data=load('policy.json')
policy_data['dev_lane']={'lane_id':'new7-local-ocr-20261021','sources':[
    {'source_id':r['derived_source_id']} for r in records]}
save('policy-ocr.json',policy_data)
policy=load_admission_policy(HERE/'policy-ocr.json',allow_dev_lane=True)
now=datetime.fromisoformat(load('authorization.json')['recorded_at'])
results=load('ocr-build-results.json') if (HERE/'ocr-build-results.json').exists() else []
with PgStore(TARGET_DSN,sandbox_db=TARGET) as store:
    for row in records:
        if any(r['source_id']==row['derived_source_id'] and r['outcome']=='published' for r in results):
            store.put_source_checkpoint(row['derived_source_id'],'local-ocr-provenance-1',
                                        json.dumps(row,ensure_ascii=False,sort_keys=True))
            continue
        sid=row['derived_source_id']; path=Path(row['derived_path'])
        assert hashlib.sha256(path.read_bytes()).hexdigest()==sid
        assert hashlib.sha256(Path(row['parent_path']).read_bytes()).hexdigest()==row['parent_source_id']
        name=Path(row['parent_path']).stem+'【本地OCR衍生】.pdf'
        domain=ResearchDomain.COMPANY if '贵州茅台' in name else ResearchDomain.INDUSTRY
        review_id='new7-ocr-user-20261021-'+sid
        store.put_reviewed_decision(ReviewedDecision(
            review_id,sid,'U: seven-file publication request; OCR derivation recorded by Codex',now,
            ReviewDecision.ADMITTED,
            'Local OCR derivative of user-supplied source '+row['parent_source_id']+
            '; original bytes preserved. Scope follows the seven-file publication request. '
            'OCR text is not a human-verified transcription; provenance: '+str(HERE/'ocr-provenance.json'),
            material_type=MaterialType.RESEARCH_REPORT,research_domain=domain))
        entry=PlanEntry(str(path),original_name=name,domain_hint=domain,review_decision_ids=(review_id,))
        outcome=execute_builds(store,plan_builds([entry],policy=policy),policy=policy,
            archive_root=ARCHIVE,owner_id='new7-ocr-publisher',now=datetime.now(UTC),lease=DEFAULT_LEASE).outcomes[0]
        assert outcome.build is not None
        store.put_source_checkpoint(sid,'local-ocr-provenance-1',
                                    json.dumps(row,ensure_ascii=False,sort_keys=True))
        build=outcome.build
        item={'source_id':sid,'parent_source_id':row['parent_source_id'],'path':str(path),
              'original_name':name,'build_id':build.build_id,'units':outcome.unit_count,
              'chunks':outcome.chunk_count,'outcome':'built','quality_report':json.loads(build.quality_report),
              'domain_hint':domain.value,'material_type':'research_report','ocr':True}
        results=[r for r in results if r['source_id']!=sid]+[item];save('ocr-build-results.json',results)
        gaps=blocking_gaps(gap_records_of(build))
        if gaps:
            acceptance=TextPublication(sid,build.build_id,canonical_fingerprint(asdict(build)),
                'codex:user-authorized-new7-local-ocr',now.isoformat(),str(HERE/'authorization.json'),
                tuple(r.key for r in gaps))
            store.put_text_publication(acceptance)
            item['text_publication_id']=acceptance.acceptance_id
        check_build_publishable(store,build.build_id)
        pub=publish_build(store,build.build_id,activated_at=datetime.now(UTC),owner_id='new7-ocr-publisher',
                          operator='codex:user-authorized-new7-local-ocr')
        item.update(outcome='published',generation=pub.generation,
                    gaps=[g.as_payload() for g in gap_records_of(build,store=store)])
        save('ocr-build-results.json',results)
        print(json.dumps(item,ensure_ascii=False),flush=True)
