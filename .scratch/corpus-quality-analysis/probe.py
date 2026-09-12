"""Read-only corpus diagnosis; no LLM calls or database writes.

Run: uv run python .scratch/corpus-quality-analysis/probe.py
"""

from collections import Counter
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
import pymupdf

from plugins.corpus.claims import PROMPT_MAX_CHARS, is_flat_table
from plugins.corpus.claims_v2 import ClaimRecord, apply_lint, records_from_payload
from plugins.corpus.ingest import _strip_boilerplate
from plugins.corpus.service import CorpusService


def main():
    load_dotenv('.env')
    service = CorpusService()
    with service._connect() as conn:
        conn.read_only = True
        conn.isolation_level = __import__('psycopg').IsolationLevel.REPEATABLE_READ
        with conn.cursor() as cur:
            cur.execute('SELECT doc_id,title,source_path,mime,status,content_hash,published FROM documents')
            docs = cur.fetchall()
            cur.execute('SELECT doc_id,seq,locator,text FROM blocks ORDER BY doc_id,seq')
            blocks = cur.fetchall()
            cur.execute('SELECT claim_id,doc_id,seq,kind,metric,value_num,unit,period,as_of,tickers,claim_text,value_text FROM claims')
            claims = cur.fetchall()
            cur.execute('SELECT status,count(*) AS n FROM claim_block_runs GROUP BY status')
            runs = cur.fetchall()
            cur.execute('SELECT count(*) AS n FROM claims_v2')
            v2_n = cur.fetchone()['n']
    by_id = {d['doc_id']: d for d in docs}
    nonempty = [b for b in blocks if b['text'].strip()]
    long = [b for b in blocks if len(b['text']) > PROMPT_MAX_CHARS]
    duplicates = Counter((b['doc_id'], b['locator']) for b in blocks)
    report = {
        'counts': {'documents': len(docs), 'blocks': len(blocks), 'claims': len(claims), 'claims_v2': v2_n},
        'document_status': dict(Counter(d['status'] for d in docs)),
        'document_mime': dict(Counter(d['mime'] for d in docs)),
        'block_runs': runs,
        'block_quality': {
            'empty': len(blocks)-len(nonempty),
            'nonempty_under_100_chars': sum(len(b['text']) < 100 for b in nonempty),
            'over_prompt_limit': len(long),
            'prompt_limit': PROMPT_MAX_CHARS,
            'omitted_characters_if_each_block_prompted': sum(len(b['text'])-PROMPT_MAX_CHARS for b in long),
            'all_characters': sum(len(b['text']) for b in blocks),
            'flat_tables': sum(is_flat_table(b['text']) for b in blocks),
            'table_appended_blocks': sum('[表格]' in b['text'] for b in blocks),
            'appended_tables_beyond_prompt': sum('[表格]' in b['text'] and b['text'].index('[表格]') >= PROMPT_MAX_CHARS for b in blocks),
            'duplicate_locators': [{'doc_id': k[0], 'locator': k[1], 'n': v} for k,v in duplicates.items() if v>1],
        },
        'claim_fields': {k: sum(c[k] is None or c[k] == '' or c[k] == [] for c in claims) for k in ['metric','value_num','unit','period','as_of','tickers']},
        'claims_by_kind': dict(Counter(c['kind'] for c in claims)),
    }
    numeric = [c for c in claims if c['value_num'] is not None]
    report['numeric_claims'] = {'n': len(numeric), 'missing_unit': sum(not c['unit'] for c in numeric), 'missing_period':sum(not c['period'] for c in numeric)}
    report['long_examples'] = [{'doc_id':b['doc_id'],'locator':b['locator'],'chars':len(b['text']),'title':by_id[b['doc_id']]['title']} for b in sorted(long,key=lambda b:len(b['text']),reverse=True)[:5]]

    # Deterministic counterexamples at real production function seams.
    report['counterexamples'] = {'integer_cleaning': {'input':'Revenue\n100\n120\nGrowth\n20%', 'output':_strip_boilerplate('Revenue\n100\n120\nGrowth\n20%')}}
    base = ClaimRecord(doc_id='probe',source_rev='probe',seq=1,locator='1',claim_text='Company revenue is 100',evidence_quote='Company revenue is 100',scope='company',subject='600519.SH',metric='revenue',value_text='100',value_num=Decimal('100'))
    variants = {
        'missing_unit_and_period': (base,'Company revenue is 100'),
        'invented_table': (replace(base,evidence_kind='table',table_ref={'row':'invented'},evidence_quote='Fabricated revenue is 100'),'Unrelated source with no figures'),
        'numeric_substring': (replace(base,claim_text='Company revenue is 20',evidence_quote='Company revenue is 120',value_text='20',value_num=Decimal('20')),'Company revenue is 120'),
        'wrong_subject': (replace(base,subject='000001.SZ'),'Company revenue is 100'),
    }
    for name,(record,body) in variants.items():
        verdict = apply_lint(record,block_text=body)
        report['counterexamples'][name] = {'quality_status':verdict.quality_status,'reason_codes':verdict.reason_codes}
    unit = records_from_payload([{'claim_text':'Company revenue 2 亿元','scope':'company','subject':'600519.SH','metric':'revenue','value_text':'2 亿元','evidence_quote':'Company revenue 2 亿元'}],doc_id='probe',source_rev='probe',seq=1,locator='1',doc_kind='company',model=None)[0]
    report['counterexamples']['unit_projection'] = {'value_num':str(unit.value_num),'unit_raw':unit.unit_raw,'unit':unit.unit,'quality_status':apply_lint(unit,block_text='Company revenue 2 亿元').quality_status}

    local_docs = []
    for d in docs:
        path=Path(d['source_path'])
        if not path.is_file():
            # Stored paths may come from Windows; match only an exact filename.
            filename=d['source_path'].replace('\\','/').split('/')[-1]
            path=Path('data/corpus')/filename
        if path.is_file() and path.suffix.lower()=='.pdf': local_docs.append((d,path))
    report['local_pdf_count'] = len(local_docs)
    removed_pages=0
    removed_integer_lines=0
    raw_pages=0
    image_only_pages=0
    low_text_pages_in_ok_docs=0
    for d,path in local_docs:
        with pymupdf.open(path) as pdf:
            for page in pdf:
                raw=page.get_text('text')
                raw_pages+=1
                ints=[s.strip() for s in raw.splitlines() if re.fullmatch(r'\s*-?\s*\d+\s*-?\s*',s)]
                removed_pages+=bool(ints)
                removed_integer_lines+=len(ints)
                if len(raw.strip())<50:
                    image_only_pages+=bool(page.get_images())
                    low_text_pages_in_ok_docs+=d['status']=='ok'
            if d['doc_id']=='2026-08-16_6f14cc14':
                page=pdf[2]
                raw=page.get_text('text')
                report['maotai_page3']={'path':str(path),'raw_chars':len(raw),'clean_chars':len(_strip_boilerplate(raw)),'removed_integer_lines':[s.strip() for s in raw.splitlines() if re.fullmatch(r'\s*-?\s*\d+\s*-?\s*',s)],'raw_start':raw[:1800]}
    report['raw_pdf_scan']={'pages':raw_pages,'pages_with_integer_lines_cleaner_removes':removed_pages,'integer_lines_cleaner_removes':removed_integer_lines,'low_text_with_images':image_only_pages,'low_text_pages_in_ok_docs':low_text_pages_in_ok_docs,'note':'Counts include real page numbers and chart ticks; not all removed lines are financial facts.'}
    print(json.dumps(report,ensure_ascii=False,indent=2,default=str))


if __name__ == '__main__':
    main()
