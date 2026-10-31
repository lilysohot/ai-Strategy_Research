"""Archive page-direction evidence and generate a separate pending review pack."""
import hashlib
import html
import json
import copy
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
RUN=ROOT/'outputs/v1'
OUT=RUN/'results'


def read(path):return json.loads(path.read_text(encoding='utf8'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    with path.open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2)


def main():
    manifest=read(OUT/'manifest.json');records=read(OUT/'records.json');summary=read(OUT/'summary.json')
    assert len(records)==18 and len({r['id'] for r in records})==18
    assert manifest==read(RUN/'inputs/manifest.json')
    assert digest(RUN/'inputs/checks.json')==manifest['checks_sha256']
    assert read(OUT/'checks.json')==read(RUN/'inputs/checks.json')
    assert all(digest(REPO/p)==sha for p,sha in manifest['code_sha256'].items())
    assert all(digest(RUN/'inputs'/d['input'])==d['sha256'] for d in manifest['documents'])
    assert all(digest(OUT/(r['id']+'.json'))==r['sha256'] for r in records)
    documents={d['id']:d for d in manifest['documents']}
    compact=[];sections=[];rows=[]
    for r in records:
        d=documents[r['document']];decision=read(OUT/(r['id']+'.json')).get('decision',{})
        support=[{'correction_clockwise':c['correction_clockwise'],**c['support']} for c in decision.get('candidates',[])]
        compact.append({**r,'relative_margin':decision.get('relative_margin'),'axis':decision.get('axis'),
                        'language_evidence':support})
        key=r['id'];source=Image.open(RUN/'inputs'/(d['id']+'.png'))
        presented=source.rotate(-r['rotation'],expand=True)
        presented.save(OUT/(key+'-input.png'))
        corrected='方向未知：不生成权威校正结果；候选仍保存在证据 JSON。'
        if r['status']=='oriented':
            result=presented.rotate(-r['correction_clockwise'],expand=True)
            result.save(OUT/(key+'-corrected.png'))
            corrected=f'<a href="{key}-corrected.png"><img src="{key}-corrected.png" alt="算法校正后"></a>'
        anchors=''.join('<li>'+str(c['correction_clockwise'])+'°：'+str(c['support']['anchor_count'])+
                        ' 个文字锚点；证据权重 '+f'{c["support"]["mass"]:.1f}'+'</li>' for c in decision.get('candidates',[]))
        detail=''.join('<tr><td>'+html.escape(c['id'])+'</td><td>'+html.escape(c['expected'])+'</td><td>'+
                       html.escape(c['actual'])+'</td><td>'+str(c['matched'])+'</td></tr>' for c in r['score']['checks'])
        sections.append(f'<details id="{key}"><summary>{key} · {r["status"]} · 校正 {r["correction_clockwise"]}° · 检查 {r["score"]["matched"]}/{r["score"]["total"]}</summary><p>{html.escape(d["name"])}；人工复核仍待处理。<a href="{key}.json">原始候选、文字框和方向证据</a></p><ul>{anchors}</ul><div class="images"><div><h3>送入模块的图像</h3><a href="{key}-input.png"><img src="{key}-input.png" alt="输入图像"></a></div><div><h3>模块输出</h3>{corrected}</div></div><table><tr><th>检查项</th><th>预先冻结值</th><th>输出</th><th>匹配</th></tr>{detail}</table></details>')
        rows.append(f'<tr><td><a href="#{key}">{key}</a></td><td>{r["expected_status"]}</td><td>{r["status"]}</td><td>{r["correction_clockwise"]}</td><td>{r["score"]["matched"]}/{r["score"]["total"]}</td><td>{r["passed"]}</td></tr>')
    evidence={'manifest':manifest,'records':compact,'summary':summary,
              'reader_and_algorithm_files_unchanged':len(manifest['code_sha256']),
              'input_copies_unchanged':True,'human_review':'pending','production_ingestion':False,
              'default_reader_changed':False,'live_sandbox_version':'unconfirmed',
              'interpretation':'Known regression only. Direction confidence is not text accuracy. Pure numeric, blank and conflicting pages must abstain.'}
    if (OUT/'runtime.json').exists():
        evidence['observed_container']=read(OUT/'runtime.json')
        prior=read(REPO/'experiments/rapidocr-shadow-20261031/evidence.json')['summary']
        assert evidence['observed_container']['image_id']==prior['image_id']
        evidence['model_manifest']=prior['model_manifest']
    write(OUT/'evidence.json',evidence)
    archived=copy.deepcopy(evidence)
    for r in archived['records']:
        for candidate in r['language_evidence']:
            for anchor in candidate['anchors']:anchor.pop('text',None)
    if not (ROOT/'evidence.json').exists():write(ROOT/'evidence.json',archived)
    write(OUT/'review.json',{'reviewer':None,'reviewed_at':None,'production_ingestion':False,
                           'pages':[{'document':d['id'],'sha256':d['sha256'],'decision':'pending',
                                     'orientation_correct':None,'numbers_correct':None,'body_complete':None,
                                     'reading_order_correct':None,'table_association_correct':None,'notes':''}
                                    for d in manifest['documents'] if not d.get('synthetic',False)]})
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>整页方向判断与校正</title><style>body{font:16px/1.6 system-ui;margin:30px;background:#f6f6f3;color:#25323a}main{max-width:1350px;margin:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:8px;border:1px solid #ccd4d9}th{background:#e9eff1}details{margin:24px 0;padding:20px;background:white;border:1px solid #ccd4d9}summary{cursor:pointer;font-weight:600}.images{display:grid;grid-template-columns:1fr 1fr;gap:25px}.images img{width:100%;max-height:700px;object-fit:contain}a{color:#245b76}</style><main><h1>整页方向判断与校正 · 隔离回归</h1><p>多行非纯数字文字参与定向；证据不足返回 unknown。先校正整页，再关闭单行方向分类。模块只接收图片，不读取测试角度或答案。</p><p>4 张真实页 + 1 张合成符号页的三个方向，共 15 个识别回归；另有空白、纯数字、混排三个拒绝判断对照。机器检查通过不代表全文或人工验收通过。</p><p><a href="review.json">人工复核模板</a> · <a href="summary.json">运行摘要</a> · <a href="manifest.json">冻结输入及参数</a> · <a href="evidence.json">完整证据摘要</a></p><table><tr><th>案例</th><th>预期行为</th><th>模块行为</th><th>顺时针校正角度</th><th>数值/文本检查</th><th>机器回归</th></tr>'''+''.join(rows)+'</table>'+''.join(sections)+'</main></html>'
    (OUT/'review.html').write_text(page,encoding='utf8')
    print(json.dumps(summary))


if __name__=='__main__':main()
