"""Supplementary diagnostics, explicitly excluded from the preregistered primary score."""
import json,re,unicodedata
from pathlib import Path
root=Path(__file__).parent;out=root/'outputs'
refs=json.loads((out/'reference-effective.json').read_text(encoding='utf8'))['pages']
norm=lambda t: re.sub(r'\s+','',unicodedata.normalize('NFKC',t)).translate(str.maketrans({'–':'-','—':'-','−':'-'}))
keys=[]
for id,spec in refs.items():
    run=json.loads((out/'runs'/f'{id}-r1.json').read_text(encoding='utf8'))
    text=norm(run['text'])
    for key in spec['keys']:keys.append({'id':id,'key':key,'present':norm(key) in text})
failures=[]
cases={
    'd054-p01':{'original':'estimate it jumps to ~8.3%/~12.2% of total revenue in 2026/2027 on the VPD ramp,',
                'ocr_fragment':'esa    /     m  s  nnp','kind':'Body line garbled; native extraction retains the original so OCR replacement would harm it.'},
    'd068-p03':{'original':'2026/27/28E EPS rise by c.1~3% on our stronger sales outlook. Our 12-month target',
                'ocr_fragment':'2o2  o   s    o   et','kind':'Body line garbled in scanned English page; main-column ordering alone cannot recover it.'}
}
for id,case in cases.items():
    run=json.loads((out/'runs'/f'{id}-r1.json').read_text(encoding='utf8'))
    index=run['lines'].index(case['ocr_fragment'])
    failures.append({'id':id,**case,'model_score':run['scores'][index],'box':run['boxes'][index],
                     'scope':'Post-hoc source-verified example outside frozen excerpts; not added to primary CER.'})
unit=json.loads((out/'runs/d066-p01-r1.json').read_text(encoding='utf8'))
index=next(i for i,t in enumerate(unit['lines']) if '6.4TOPS' in t)
failures.append({'id':'d066-p01','original':'6.4TOPS/W@INT8','ocr_fragment':unit['lines'][index],
                 'model_score':unit['scores'][index],'kind':'Extra W in technical unit despite high line confidence.'})
result={'normalized_key_method':'Post-hoc NFKC, whitespace removal, common dash variants to ASCII hyphen. No number/unit correction. Supplementary only; strict primary gate remains unchanged.',
        'normalized_keys_total':len(keys),'normalized_keys_present':sum(k['present'] for k in keys),
        'normalized_missing_keys':[k for k in keys if not k['present']], 'failure_examples':failures,
        'source_text_layer_findings':{'d021-p02':'Native text contains mostly numerals; visible Chinese body absent.',
                                      'd021-p03':'Native text contains mostly numerals; visible Chinese body absent.'}}
(out/'posthoc-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k not in ('failure_examples','source_text_layer_findings')},ensure_ascii=False))
