from pathlib import Path
import json, shutil
root=Path('/home/administrator/FrontierAgent/.scratch/m6-current-review-20260923').resolve()
for p in root.iterdir():
    if p.is_dir() and (p.name.endswith('-tmp') or p.name in ('__pycache__','.pytest_cache')):
        target=p.resolve()
        target.relative_to(root)
        assert target!=root
        shutil.rmtree(target)
for name in ('m6-spec-fetch-probe.py','m6-spec-target-diff.py'):
    p=root/name
    s=p.read_text(encoding='utf-8-sig')
    s=s.replace("Path('/tmp/m6-spec-fetch-probe-results.json')", "Path(__file__).resolve().parent / 'm6-spec-fetch-probe-results.json'")
    # Parentheses are necessary where a method is called on the path expression.
    s=s.replace("Path(__file__).resolve().parent / 'm6-spec-fetch-probe-results.json'.", "(Path(__file__).resolve().parent / 'm6-spec-fetch-probe-results.json').")
    p.write_text(s)
v=json.loads((root/'product-path-probe.json').read_text())
print(json.dumps({'questions':len(v['rows']),'positive_raw_empty':sum(not r['negative'] and r['raw_hits']==0 for r in v['rows']),'negative_or_hits':sum(r['negative'] and r['or_hits']>0 for r in v['rows']),'different_chunks':len(v['different_chunk_evidence'])}))
