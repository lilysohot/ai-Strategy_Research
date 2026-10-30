import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'outputs'
manifest={r['id']:r for r in json.loads((OUT/'manifest.json').read_text(encoding='utf8'))}
rows=json.loads((OUT/'evaluation.json').read_text(encoding='utf8'))
lines=['# 正文组件逐页复核索引','',
       '页码均为 PDF 物理页码（从 1 开始）。指标为固定抽样片段，控制页不计正文错误率；`needs_review` 为待核验提示。', '',
       '| 页面 | 新增 | 来源 | 状态 | 片段错误/字数 | 关键内容命中 | 秒 | 自动分栏 | 异常规则 |',
       '|---|---|---|---|---:|---:|---:|---|---|']
for r in rows:
    counts=f"{r['edits']}/{r['chars']}" if r['chars'] else '控制页'
    keys=f"{r['keys_total']-len(r['missing_keys'])}/{r['keys_total']}"
    issues=', '.join(f'{k}×{v}' for k,v in r['issue_codes'].items()) or '无'
    lines.append(f"| [{r['id']}](outputs/{r['id']}.txt) | {'是' if r['held_out'] else '否'} | {r['source']} | {r['status']} | {counts} | {keys} | {r['wall_seconds']:.3f} | {'是' if r['layout'] else '否'} | {issues} |")
lines+=['','原冻结参考 d065-p04 为 1/81；表中使用源图复核后的参考（0/81），详见 reference-errata.json。', '', '## 样本文件对应','']
seen=set()
for item in manifest.values():
    if item['doc_id'] in seen: continue
    seen.add(item['doc_id'])
    lines.append(f"- `{item['doc_id']}`：{item['name']}；SHA-256 `{item['sha256']}`。")
lines+=['','原始路径见 outputs/manifest.json；源文件未修改。原 26 页预览位于 ../rapidocr-expanded-20261030/outputs/previews，新增 4 页预览位于本实验 outputs。', '',
        '原始 OCR、识别框、置信度、原生文字和完整异常证据位于 outputs/runs/<页面>.json。']
(ROOT/'PAGE_REVIEW.zh-CN.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
files=[p for p in ROOT.iterdir() if p.is_file() and p.suffix in ('.py','.json','.ps1')]
provenance={'code_and_reference_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            'image_id':(OUT/'image-id.txt').read_text(encoding='utf8').strip(),
            'prior_environment':json.loads((ROOT.parent/'rapidocr-expanded-20261030/outputs/environment.json').read_text(encoding='utf8')),
            'note':'Environment metadata inherited from the same immutable image; current run isolation in run.ps1. Prior input/reference manifests in inherited metadata are historical, current selection in outputs/manifest.json.'}
(OUT/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf8')
print('Wrote page review and provenance.')
