from pathlib import Path
import hashlib,json,shutil
r=Path('/home/administrator/FrontierAgent');out=r/'.scratch/m6-repair-20260923';paths=['plugins/corpus/preparation/read_pg.py','plugins/corpus/preparation/cross_boundary.py','plugins/corpus/service.py','plugins/tools/corpus_fetch.py','tests/test_corpus_selection.py','docs/plan/corpus-ingestion-rebuild-tasks.md','docs/plan/claims-market-closed-loop-plan.md','.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py']
manifest={}
for rel in paths:
 p=r/rel;dst=out/'before'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst);manifest[rel]=hashlib.sha256(p.read_bytes()).hexdigest()
(out/'before-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
shutil.copyfile(r/'.scratch/m6-current-review-20260923/test_integrity_regressions.py',r/'tests/test_corpus_context_integrity.py')
