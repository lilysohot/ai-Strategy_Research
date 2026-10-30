"""Post-hoc manual region diagnostic. NOT an automatic layout implementation."""
import ast,json,re
from pathlib import Path
root=Path(__file__).parent;out=root/'outputs'
source=ast.parse((root.parent/'ocr-smoke-20261019/evaluate_real.py').read_text(encoding='utf8'))
scope={'re':re}
exec(compile(ast.Module(body=[n for n in source.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),'metric','exec'),scope)
norm,distance=scope['norm'],scope['excerpt_distance']
reference=json.loads((out/'reference-effective.json').read_text(encoding='utf8'))['pages']
# Relative rectangles read from source page previews, selecting only the principal text column.
rectangles={'d001-p01':[.08,.18,.65,.93],'d002-p01':[.08,.24,.59,.84],
            'd005-p01':[.13,.21,.70,.89],'d068-p01':[.08,.26,.60,.87]}
rows=[]
for key,rect in rectangles.items():
    run=json.loads((out/'runs'/f'{key}-r1.json').read_text(encoding='utf8'))
    width,height=run['render_pixels']
    chosen=[]
    for box,line in zip(run['boxes'],run['lines']):
        x=sum(p[0] for p in box)/4/width;y=sum(p[1] for p in box)/4/height
        if rect[0]<=x<=rect[2] and rect[1]<=y<=rect[3]:chosen.append((y,x,line))
    chosen.sort()
    text='\n'.join(line for _,_,line in chosen)
    (out/f'{key}-manual-column.txt').write_text(text,encoding='utf8')
    excerpts=[]
    for ref in reference[key]['excerpts']:
        edits,matched=distance(norm(ref),norm(text))
        raw,_=distance(norm(ref),norm(run['text']))
        excerpts.append({'reference':ref,'raw_edits':raw,'column_edits':edits,'chars':len(norm(ref)),'matched':matched})
    rows.append({'id':key,'rectangle_relative':rect,'excerpts':excerpts,
                 'raw_cer':sum(e['raw_edits'] for e in excerpts)/sum(e['chars'] for e in excerpts),
                 'manual_column_cer':sum(e['column_edits'] for e in excerpts)/sum(e['chars'] for e in excerpts)})
payload={'method':'Post-hoc diagnostic selecting source-inspected main column using manual coordinates and existing OCR boxes. No OCR rerun, no spelling correction. Not automatic or generalizable, and excluded from primary gates.','pages':rows}
(out/'layout-diagnostic.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
for row in rows:print(json.dumps({k:v for k,v in row.items() if k!='excerpts'}))
