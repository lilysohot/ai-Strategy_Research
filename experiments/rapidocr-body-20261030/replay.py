"""Diagnostic replay: no inference timing is attributed to cached OCR."""
import ast,json,re
from pathlib import Path
from body_reader import read_page
ROOT=Path(__file__).resolve().parent
PRIOR=ROOT.parent/'rapidocr-expanded-20261030'
OUT=ROOT/'outputs'
source=ast.parse((ROOT.parent/'ocr-smoke-20261019/evaluate_real.py').read_text(encoding='utf8'))
ns={'re':re}
exec(compile(ast.Module(body=[n for n in source.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),'metric','exec'),ns)
norm,distance=ns['norm'],ns['excerpt_distance']
ref=json.loads((PRIOR/'outputs/reference-effective.json').read_text(encoding='utf8'))

def score(text,spec):
    t=norm(text)
    return {'chars':sum(len(norm(x)) for x in spec['excerpts']),
            'edits':sum(distance(norm(x),t)[0] for x in spec['excerpts']),
            'missing_keys':[x for x in spec['keys'] if norm(x) not in t]}

def main():
    rows=[]
    for row in json.loads((PRIOR/'outputs/results.json').read_text(encoding='utf8')):
        key,raw=row['id'],row['result']
        native=(PRIOR/f'outputs/baseline-before-{key}-text.txt').read_text(encoding='utf8')
        native=re.sub(r'^\(PDF:.*?\)\s*','',native,count=1,flags=re.S)
        native=re.sub(r'<!-- page \d+ -->','',native).strip()
        reordered=read_page('',1,enabled=True,native_reader=lambda *_:'',ocr_reader=lambda *_:raw)
        hybrid=read_page('',1,enabled=True,native_reader=lambda *_:native,ocr_reader=lambda *_:raw)
        rows.append({'id':key,'source':hybrid['source'],'layout':reordered['layout'],
                     'raw':score(raw['text'],ref['pages'][key]),
                     'reordered':score(reordered['text'],ref['pages'][key]),
                     'hybrid':score(hybrid['text'],ref['pages'][key]),
                     'issues':[x['code'] for x in hybrid['issues']]})
    (OUT/'replay.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    for r in rows: print(r['id'],r['source'],[r[k]['edits'] for k in ('raw','reordered','hybrid')],r['layout'])

if __name__=='__main__': main()
