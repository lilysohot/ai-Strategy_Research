from run_batch import *
from plugins.corpus.service import CorpusService
from dataclasses import asdict
import re
report=load('ocr-audit-readonly.json')
checks=[]
with psycopg.connect(TARGET_DSN) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    for r in load('ocr-build-results.json'):
        units=conn.execute('SELECT unit_id,raw_text FROM corpus.corpus_units WHERE build_id=%s',(r['build_id'],)).fetchall()
        keys=('高股姑','202604','Moutal','AISKSKS')
        found=[]
        for uid,txt in units:
            compact=re.sub(r'\s+','',txt)
            if any(k in compact for k in keys):found.append({'unit_id':uid,'text':txt})
        chunk=conn.execute('SELECT chunk_id FROM corpus.corpus_chunks WHERE build_id=%s ORDER BY chunk_id LIMIT 1',(r['build_id'],)).fetchone()[0]
        evidence=CorpusService(TARGET_DSN).fetch_verbatim('cv2:'+r['build_id'],'chunk:'+chunk)
        fields=list(asdict(evidence))
        checks.append({'source_id':r['source_id'],'persisted_sample_errors':found,'fetch_evidence_fields':fields,
                       'explicit_ocr_origin_or_review_field_present':any('ocr' in f or 'review' in f or 'provenance' in f for f in fields)})
report['downstream_checks']=checks
report['conclusion']='OCR pipeline execution verified; OCR accuracy not accepted. Image gap grading and downstream OCR disclosure need work before treating this as a regular ingestion path.'
save('ocr-audit-readonly.json',report)
print(json.dumps(checks,ensure_ascii=False,indent=2))
