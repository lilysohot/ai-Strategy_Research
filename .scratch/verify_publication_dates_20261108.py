import json, os, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from dotenv import load_dotenv
load_dotenv('.env')
import psycopg
from plugins.corpus.service import dsn
from plugins.corpus.retrieval.native_live import _date
from plugins.corpus.publication_dates import publication_matches
root = Path(os.environ['CORPUS_NATIVE_INDEX'])
manifest = json.loads((root if root.is_file() else root/'manifest.json').read_text())
allowlist = manifest['source_allowlist']
sql = '''SELECT p.source_id,p.active_build_id,s.original_names,
m.confirmed_publication_date::text,a.metadata_snapshot,
sa.metadata_snapshot AS source_snapshot,m.field_evidence
FROM corpus.corpus_publications p JOIN corpus.corpus_sources s USING(source_id)
JOIN corpus.corpus_builds b ON b.build_id=p.active_build_id
JOIN corpus.corpus_admissions a ON a.decision_id=b.decision_id
JOIN corpus.corpus_admissions live ON live.decision_id=p.current_decision_id
JOIN corpus.corpus_admissions sa ON sa.decision_id=s.current_decision_id
LEFT JOIN corpus_retrieval.source_metadata m ON m.source_id=p.source_id
WHERE p.source_id=ANY(%s::text[]) AND live.decision='in_scope'
AND sa.decision='in_scope' ORDER BY p.source_id'''
with psycopg.connect(dsn(), connect_timeout=10) as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    target = conn.execute('SELECT current_database()').fetchone()[0]
    assert target == os.environ['CORPUS_NATIVE_TARGET_DB']
    cols = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='corpus_retrieval' AND table_name='source_metadata'").fetchall()
    print('metadata_columns', [x[0] for x in cols])
    if 'field_evidence' not in [x[0] for x in cols]:
        sql = sql.replace('m.field_evidence', 'NULL')
    rows = conn.execute(sql, (allowlist,)).fetchall()
    records=[]
    for sid,bid,names,reviewed,snapshot,source_snapshot,evidence in rows:
        rp=(snapshot or {}).get('report_publication') or {}
        value,basis=_date(names,reviewed,rp.get('value'))
        records.append(dict(source_id=sid,build_id=bid,names=names,date=value,basis=basis,
            reviewed_date=reviewed,admission_publication=rp,source_snapshot=source_snapshot,reviewed_evidence=evidence))
    counts=Counter(r['basis'] for r in records)
    summary=dict(checked_at=datetime.now(timezone.utc).isoformat(), database=target,
        native_mode=os.environ.get('CORPUS_NATIVE_RETRIEVAL'),index=str(root),
        allowlist_count=len(allowlist),active_count=len(records),counts=dict(counts),
        explicit_filter_eligible=sum(publication_matches(r,None,None) for r in records),
        admission_status=dict(Counter((r['admission_publication'].get('status') or 'absent') for r in records)),
        explicit_dates=dict(Counter(r['date'] for r in records if publication_matches(r,None,None))),
        total_sources=conn.execute('SELECT count(*) FROM corpus.corpus_sources').fetchone()[0],
        total_active_publications=conn.execute('SELECT count(*) FROM corpus.corpus_publications WHERE active_build_id IS NOT NULL').fetchone()[0])
    out=Path('.scratch/publication-date-audit-20261108.json')
    out.write_text(json.dumps(dict(summary=summary,sources=records),ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('reviewed_date_evidence',json.dumps([dict(name=r['names'][0], date=r['date'], evidence=r['reviewed_evidence']) for r in records if publication_matches(r,None,None)],ensure_ascii=False,indent=2))


