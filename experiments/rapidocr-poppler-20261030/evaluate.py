import ast,collections,copy,hashlib,json,re,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'outputs'
PRIOR=ROOT.parent/'rapidocr-expanded-20261030'
source=ast.parse((ROOT.parent/'ocr-smoke-20261019/evaluate_real.py').read_text(encoding='utf8'))
ns={'re':re};exec(compile(ast.Module(body=[n for n in source.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),'metric','exec'),ns)
norm,distance=ns['norm'],ns['excerpt_distance']

def write(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def score(text,spec):
    text=norm(text)
    excerpts=[]
    for x in spec['excerpts']:
        edits,match=distance(norm(x),text)
        excerpts.append({'reference':x,'chars':len(norm(x)),'edits':edits,'match':match})
    return {'chars':sum(x['chars'] for x in excerpts),'edits':sum(x['edits'] for x in excerpts),
            'missing_keys':[x for x in spec['keys'] if norm(x) not in text], 'excerpts':excerpts}

def main():
    reference=json.loads((ROOT/'reference.json').read_text(encoding='utf8'))
    frozen=copy.deepcopy(reference)
    for c in json.loads((ROOT/'reference-errata.json').read_text(encoding='utf8'))['corrections']:
        text=reference['pages'][c['id']]['excerpts'][c['index']]
        assert c['old'] in text
        reference['pages'][c['id']]['excerpts'][c['index']]=text.replace(c['old'],c['new'],1)
    write('reference-effective.json',reference)
    refs={**json.loads((PRIOR/'outputs/reference-effective.json').read_text(encoding='utf8'))['pages'],**reference['pages']}
    records=json.loads((OUT/'results.json').read_text(encoding='utf8'))
    rows=[]
    for record in records:
        key=record['id']; spec=refs[key]; hybrid=record['hybrid'];ordered=record['ordered_ocr']
        raw=ordered['ocr_original']['text']
        baseline=(OUT/f'baseline-before-{key}-auto.txt').read_text(encoding='utf8')
        baseline=re.split(r'<!-- page[^>]*-->',baseline,maxsplit=1)[-1]
        row={'id':key,'new_page':record['new_page'],'route':hybrid['source'],'status':hybrid['status'],
             'layout':ordered['layout'],'key_count':len(spec['keys']),
             'hybrid':score(hybrid['text'],spec),'raw_ocr':score(raw,spec),
             'ordered_ocr':score(ordered['text'],spec),'production_auto':score(baseline,spec)}
        rows.append(row)
        if record['new_page']:
            row['frozen_hybrid']=score(hybrid['text'],frozen['pages'][key])
            row['frozen_ordered_ocr']=score(ordered['text'],frozen['pages'][key])
    write('evaluation.json',rows)
    def aggregate(group):
        out={'pages':len(group),'body_pages':sum(bool(r['hybrid']['chars']) for r in group),
             'routes':dict(collections.Counter(r['route'] for r in group))}
        for mode in ('hybrid','raw_ocr','ordered_ocr','production_auto'):
            chars=sum(r[mode]['chars'] for r in group);edits=sum(r[mode]['edits'] for r in group)
            count=sum(r['key_count'] for r in group);present=count-sum(len(r[mode]['missing_keys']) for r in group)
            out[mode]={'chars':chars,'edits':edits,'cer':edits/chars if chars else None,
                       'keys_total':count,'keys_present':present}
        return out
    groups={'old26':aggregate([r for r in rows if not r['new_page']]),'new8':aggregate([r for r in rows if r['new_page']])}
    probes=json.loads((OUT/'partial-native-probes.json').read_text(encoding='utf8'))
    detected=sum(r['ocr_triggered'] or r['needs_review'] for r in probes)
    checks=json.loads((OUT/'checks.json').read_text(encoding='utf8'))
    renders=json.loads((OUT/'render-regression.json').read_text(encoding='utf8'))
    gates=reference['gates']; new=groups['new8']['hybrid']
    acceptance={'new_body_excerpt_cer':new['cer']<=gates['new_body_excerpt_cer_max'],
                'new_key_presence':new['keys_present']/new['keys_total']>=gates['new_key_presence_min'],
                'partial_native_detection':bool(probes) and detected/len(probes)>=gates['partial_native_detection_min'],
                'production_outputs_unchanged':checks['baseline_outputs_equal'] and renders['outputs_equal'] and renders['image_hashes_equal'] and renders['rendered_pages']==34}
    fresh=[x['result'] for x in json.loads((OUT/'fresh-ocr.json').read_text(encoding='utf8'))]
    summary={'groups':groups,'partial_native':{'cases':len(probes),'detected':detected,'missed':len(probes)-detected},
             'frozen_reference_scores':{mode:{'chars':sum(r[mode]['chars'] for r in rows if r['new_page']),
                                            'edits':sum(r[mode]['edits'] for r in rows if r['new_page'])}
                                        for mode in ('frozen_hybrid','frozen_ordered_ocr')},
             'gates':acceptance,'ready_for_unattended_use':all(acceptance.values()),
             'fresh_ocr_timing':{'pages':len(fresh),'total_seconds':sum(x['wall_seconds'] for x in fresh),
              'median_seconds':statistics.median(x['wall_seconds'] for x in fresh),'max_seconds':max(x['wall_seconds'] for x in fresh),
              'max_sampled_tree_mib':max(x['sampled_peak_tree_mib'] for x in fresh)},
             'timing_scope':'Only eight forced OCR inference runs. Hybrid selection and ordering used cached OCR; no end-to-end hybrid timing claim.'}
    write('summary.json',summary)
    inventory=json.loads((PRIOR/'outputs/inventory.json').read_text(encoding='utf8'))
    changed=[d['name'] for d in inventory if hashlib.sha256(Path(d['path']).read_bytes()).hexdigest()!=d['sha256']]
    write('source-isolation.json',{'files_checked':len(inventory),'changed_files':changed}); assert not changed
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
