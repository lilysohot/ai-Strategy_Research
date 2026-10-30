"""Score actual hybrid outputs separately from cached OCR-only layout replay."""
import collections,copy,hashlib,json,math,statistics
from pathlib import Path
from replay import ROOT,PRIOR,OUT,ref,score,norm

def write(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def aggregate(rows):
    chars=sum(r['chars'] for r in rows); times=sorted(r['wall_seconds'] for r in rows)
    return {'pages':len(rows),'body_pages':sum(bool(r['chars']) for r in rows),
            'chars':chars,'edits':sum(r['edits'] for r in rows),
            'cer':sum(r['edits'] for r in rows)/chars if chars else None,
            'keys_total':sum(r['keys_total'] for r in rows),
            'keys_present':sum(r['keys_total']-len(r['missing_keys']) for r in rows),
            'routes':dict(collections.Counter(r['source'] for r in rows)),
            'review_pages':sum(r['needs_review'] for r in rows),
            'total_seconds':sum(times),'median_seconds':statistics.median(times),
            'p95_seconds':times[math.ceil(.95*len(times))-1],
            'max_peak_mib':max(r['peak_mib'] for r in rows)}

def main():
    heldout=json.loads((ROOT/'heldout-reference.json').read_text(encoding='utf8'))
    frozen_heldout=copy.deepcopy(heldout)
    for correction in json.loads((ROOT/'reference-errata.json').read_text(encoding='utf8'))['corrections']:
        values=heldout['pages'][correction['id']][correction['field']]
        assert values[correction['index']]==correction['old']
        values[correction['index']]=correction['new']
    write('heldout-reference-effective.json',heldout)
    refs={**ref['pages'],**heldout['pages']}
    records=json.loads((OUT/'results.json').read_text(encoding='utf8'))
    rows=[]
    for row in records:
        key=row['id']; result=row['result']; spec=refs[key]
        rows.append({'id':key,'held_out':row['held_out'],**score(result['text'],spec),
                     'frozen_reference_edits':score(result['text'],frozen_heldout['pages'][key])['edits'] if row['held_out'] else score(result['text'],spec)['edits'],
                     'keys_total':len(spec['keys']),'source':result['source'],
                     'language':spec['language'],'status':result['status'],
                     'needs_review':result['needs_review'],'issue_codes':dict(collections.Counter(i['code'] for i in result['issues'])),
                     'layout':result['layout'],'wall_seconds':result['wall_seconds'],
                     'peak_mib':result['sampled_peak_tree_mib']})
    original=[r for r in rows if not r['held_out']]
    groups={'original26':aggregate(original),'heldout4':aggregate([r for r in rows if r['held_out']]),'all30':aggregate(rows)}
    for lang in ('zh','en','mixed'):
        groups[lang]=aggregate([r for r in original if r['language']==lang])
    groups['ocr26']=aggregate([r for r in original if r['source']=='ocr'])
    groups['native26']=aggregate([r for r in original if r['source']=='native'])
    write('evaluation.json',rows);write('summary.json',groups)
    audit=[]
    for known in json.loads((PRIOR/'outputs/posthoc-audit.json').read_text(encoding='utf8'))['failure_examples']:
        result=next(r['result'] for r in records if r['id']==known['id'])
        matched=[i for i in result['issues'] if norm(known['ocr_fragment']) in norm(i.get('text',''))]
        audit.append({'id':known['id'],'source':result['source'],
                      'original_present':norm(known['original']) in norm(result['text']),
                      'garble_present':norm(known['ocr_fragment']) in norm(result['text']),
                      'matching_issue_codes':[i['code'] for i in matched]})
    write('known-errors.json',audit)
    inventory=json.loads((PRIOR/'outputs/inventory.json').read_text(encoding='utf8'))
    changed=[d['name'] for d in inventory if hashlib.sha256(Path(d['path']).read_bytes()).hexdigest()!=d['sha256']]
    write('source-isolation.json',{'files_checked':len(inventory),'changed_files':changed})
    assert not changed
    print(json.dumps({'groups':groups,'known_errors':audit},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
