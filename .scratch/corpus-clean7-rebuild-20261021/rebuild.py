"""Official plan/build/check/publish, scoped to the 18 cloned active sources."""
import hashlib
from datetime import UTC,datetime
from common import *
from plugins.corpus.preparation.admission import load_admission_policy
from plugins.corpus.preparation.contract import ResearchDomain
from plugins.corpus.preparation.engine import (DEFAULT_LEASE,PlanEntry,plan_builds,execute_builds,
    check_build_publishable,publish_build,EngineError)
from plugins.corpus.preparation.repository_pg import PgStore
from plugins.corpus.service import _I2_POLICY_PATH

setup(NEW)
assert read('clone.json')['to']==NEW
dev=ROOT/'.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-dev-lane/admission-policy-dev.json'
policies={p.policy_rev:p for p in (load_admission_policy(_I2_POLICY_PATH),load_admission_policy(dev,allow_dev_lane=True))}
archive=ROOT/'data/vector-pilot-clean7-20261021/archive'
inventory=read('inventory.json')
results=read('build-results.json') if (HERE/'build-results.json').exists() else []
done={r['source_id'] for r in results}
with PgStore(connection(NEW),sandbox_db=NEW) as store:
    for item in inventory:
        sid=item['source_id']
        prior=next((r for r in results if r['source_id']==sid),None)
        if sid in done and prior['status']!='no_build':
            continue
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==sid
        policy=policies[item['admission']['policy_rev']]
        name=item['source']['original_names'][0]
        review_ids=list(item['review_decision_ids'])
        for rid in review_ids:
            review=store.get_reviewed_decision(rid)
            assert review is not None and review.source_id==sid
            if review.supersedes and review.supersedes not in review_ids:
                review_ids.append(review.supersedes)
        entry=PlanEntry(path=item['path'],original_name=name,
            domain_hint=ResearchDomain(item['admission']['research_domain']),
            review_decision_ids=tuple(review_ids))
        record={'source_id':sid,'old_build':item['old_build'],'old_schema':item['checkpoint_schema']}
        try:
            outcome=execute_builds(store,plan_builds([entry],policy=policy),policy=policy,
                archive_root=archive,owner_id='clean7-isolated-rebuild',now=datetime.now(UTC),lease=DEFAULT_LEASE).outcomes[0]
            record.update(admission=outcome.admission.decision.value,units=outcome.unit_count,chunks=outcome.chunk_count)
            if outcome.build is None:
                record['status']='no_build'
            else:
                record.update(build_id=outcome.build.build_id,clean_rev=outcome.build.clean_rev,
                    quality_report=json.loads(outcome.build.quality_report))
                check_build_publishable(store,outcome.build.build_id)
                pub=publish_build(store,outcome.build.build_id,activated_at=datetime.now(UTC),
                    owner_id='clean7-isolated-rebuild',operator='codex:user-authorized-clean7-pilot')
                record.update(status='published',generation=pub.generation)
        except EngineError as exc:
            record.update(status='blocked_by_gate',error=str(exc))
        if prior:
            record['previous_attempt']=prior
            results=[r for r in results if r['source_id']!=sid]
        results.append(record)
        save('build-results.json',results)
        print(json.dumps({k:v for k,v in record.items() if k!='quality_report'},ensure_ascii=False),flush=True)
save('build-summary.json',{'published':sum(r['status']=='published' for r in results),'results':len(results)})
