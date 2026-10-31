"""Verify frozen evidence and build a human review pack; never approve a page."""
import hashlib
import html
import json
from pathlib import Path
import shutil

from PIL import Image

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
RUN=ROOT/'outputs/batch2'
OUT=RUN/'results'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,value):
    with path.open('x',encoding='utf8') as handle:json.dump(value,handle,ensure_ascii=False,indent=2)


def main():
    manifest=read(OUT/'manifest.json');checks=read(OUT/'checks.json');records=read(OUT/'records.json')
    assert len(records)==24 and len({r['id'] for r in records})==24
    assert digest(RUN/'inputs/checks.json')==manifest['checks_sha256']
    # The runner serializes the parsed fixture again; output whitespace is not
    # byte-identical to the frozen input. Both bytes and parsed values matter.
    assert checks==read(RUN/'inputs/checks.json')
    before=read(RUN/'code-before.json')
    assert all(digest(REPO/p)==sha for p,sha in before.items())
    for d in manifest['documents']:
        assert digest(RUN/'inputs'/d['input'])==d['sha256']
        if 'source_path' in d:
            # Manifest was created in WSL, but finalization may run in Windows.
            relative=Path(d['source_path']).relative_to('/home/administrator/FrontierAgent')
            assert digest(REPO/relative)==d['sha256']
    assert all(digest(OUT/(r['id']+'.json'))==r['output_sha256'] for r in records)
    lookup={(r['document'],r['rotation'],r['mode']):r for r in records}
    groups=[];disagreements=[];agreement_errors=[]
    for synthetic in (False,True):
        for rotation in (0,90,180):
            for mode in ('cls','no-cls'):
                rs=[r for r in records if (r['synthetic'],r['rotation'],r['mode'])==(synthetic,rotation,mode)]
                groups.append({'synthetic':synthetic,'rotation':rotation,'mode':mode,
                               'matched':sum(r['score']['matched'] for r in rs),
                               'total':sum(r['score']['total'] for r in rs)})
    for d in manifest['documents']:
        for rotation in (0,90,180):
            a=lookup[(d['id'],rotation,'cls')]['score']['checks']
            b=lookup[(d['id'],rotation,'no-cls')]['score']['checks']
            for left,right in zip(a,b):
                item={'document':d['id'],'rotation':rotation,'check':left['id'],
                      'cls':left['actual'],'no_cls':right['actual'],'expected':left['expected']}
                if left['actual']!=right['actual']:disagreements.append(item)
                elif not left['matched']:agreement_errors.append(item)
    route=[]
    for d in manifest['documents']:
        if d.get('synthetic'):continue
        r=read(OUT/(d['id']+'-normal-route.json'))
        candidate=r.get('candidate',{})
        route.append({'document':d['id'],'source':candidate.get('source'),'status':candidate.get('status'),
                      'issues':candidate.get('issues'), 'coverage':candidate.get('coverage')})
    evidence={'manifest':manifest,'groups':groups,'records':records,'normal_routes':route,
              'disagreements':disagreements,'agreement_but_mismatch':agreement_errors,
              'mode_all_checks_pass':{m:all(r['status']=='ok' and r['score']['matched']==r['score']['total'] for r in records if r['mode']==m) for m in ('cls','no-cls')},
              'summary':read(OUT/'summary.json'),'reader_and_experiment_files_unchanged':len(before),
              'originals_and_copies_unchanged':True,'human_review':'pending','gray_release_ready':False,
              'live_sandbox_version':'not_verified','production_ingestion':False,
              'timing':{'candidate_worker_seconds':sum(r['seconds'] for r in records),
                        'max_sampled_worker_tree_mib':max(r['peak_tree_mib'] for r in records)},
              'scope':'Three real pages and one synthetic control; rotations are synthetic stress, forced raster OCR, not new real documents. Assistant annotations, not full transcription or human acceptance.'}
    previous=read(REPO/'experiments/rapidocr-shadow-20261031/number-evidence.json')
    evidence['known_ddog_regression']={m:previous['modes'][source]['correct'] for m,source in [('cls','baseline'),('no-cls','no-cls')]}
    evidence['known_ddog_total']=previous['modes']['baseline']['total']
    evidence['combined_gate']={m:evidence['mode_all_checks_pass'][m] and n==evidence['known_ddog_total'] for m,n in evidence['known_ddog_regression'].items()}
    write(OUT/'evidence.json',evidence)
    # Keep the committed historical summary when reproducing in a clone.
    if not (ROOT/'evidence.json').exists():write(ROOT/'evidence.json',evidence)
    write(OUT/'review.json',{'reviewer':None,'reviewed_at':None,'production_ingestion':False,
                           'pages':[{'document':d['id'],'source_sha256':d['sha256'],'decision':'pending',
                                     'numbers_units_signs':None,'body_complete':None,'reading_order':None,
                                     'table_association':None,'notes':''} for d in manifest['documents'] if not d.get('synthetic')]})
    sections=[]
    for d in manifest['documents']:
        key=d['id'];im=Image.open(RUN/'inputs'/(key+'.png'))
        shutil.copyfile(RUN/'inputs'/(key+'.png'),OUT/(key+'.png'))
        for rotation in (90,180):im.rotate(-rotation,expand=True).save(OUT/f'{key}-r{rotation}.png')
        columns=[(r,m) for r in (0,90,180) for m in ('cls','no-cls')]
        headers=''.join(f'<th>{r}° {m}<br>{lookup[(key,r,m)]["score"]["matched"]}/{len(checks[key])}</th>' for r,m in columns)
        rows=[]
        for i,c in enumerate(checks[key]):
            cells=[]
            for r,m in columns:
                result=lookup[(key,r,m)]['score']['checks']
                entry=result[i] if i<len(result) else {'matched':False,'actual':'worker failed'}
                cells.append('<td class="'+('good' if entry['matched'] else 'bad')+'">'+html.escape(entry['actual'])+'</td>')
            rows.append('<tr><td>'+c['id']+'</td><td>'+html.escape(c['expected'])+'</td>'+''.join(cells)+'</tr>')
        raw=' · '.join(f'<a href="{key}-r{r}-{m}.json">{r}° {m} 原始证据</a>' for r,m in columns)
        baseline='' if d.get('synthetic') else f'<p><a href="{key}-normal-route.json">正常路由及覆盖提示</a> · <a href="{key}-baseline-text.txt">现有 text 输出</a> · <a href="{key}-baseline-auto.txt">现有 auto 输出</a> · <a href="{key}-baseline-image.txt">现有 image 输出</a></p>'
        sections.append(f'<section><h2>{html.escape(d["name"])} · 第 {d["page"]} 页</h2><p>{"合成符号对照，不是真实研报" if d.get("synthetic") else "人工复核：待处理"}</p><p><a href="{key}.png">正向原页</a> · <a href="{key}-r90.png">90° 对照图</a> · <a href="{key}-r180.png">180° 对照图</a></p>{baseline}<p>{raw}</p><div class="scroll"><table><tr><th>固定检查项</th><th>助手转写</th>{headers}</tr>{"".join(rows)}</table></div></section>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>第二批 OCR 方向回归</title><style>body{font:15px/1.6 system-ui;margin:28px;background:#f6f6f3;color:#22313b}main{max-width:1600px;margin:auto}section{margin:28px 0;background:white;padding:22px;border:1px solid #ddd}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #d2d8dc;padding:8px;min-width:100px;max-width:260px;overflow-wrap:anywhere}th{background:#eaf0f3}.bad{background:#ffe5df}.good{background:#f1f8ef}a{color:#205b7b}</style><main><h1>第二批 OCR 方向回归 · 独立旁路</h1><p>3 份未见研报各 1 页 + 1 页合成符号对照。0°/90°/180° × 开/关方向分类，共 24 次 OCR。未更换模型、未修改默认方向设置、未正式入库。</p><p>下表检查项在推理前冻结；仅去空白比较，符号、标点差异均记为不匹配，不能把所有不匹配直接解释为数字语义错误。真实样本共 34 项，合成样本 6 项，不是完整真值。坐标逆旋转仅用于评分，没有帮 OCR 纠正页面方向。</p><p>即使两种候选一致，也不能代替源页复核。完整表格行列关联、正文完整性及最终顺序仍待人工检查。</p><p><a href="review.json">人工复核模板</a> · <a href="manifest.json">输入范围</a> · <a href="summary.json">运行摘要</a></p>'''+''.join(sections)+'</main></html>'
    (OUT/'review.html').write_text(page,encoding='utf8')
    print(json.dumps({'groups':groups,'mode_all_checks_pass':evidence['mode_all_checks_pass'],
                      'combined_gate':evidence['combined_gate'],
                      'disagreements':len(disagreements),'agreement_but_mismatch':len(agreement_errors),
                      'timing':evidence['timing'],'baseline':evidence['summary']},ensure_ascii=False))


if __name__=='__main__':main()
