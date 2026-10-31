"""Verify the immutable run and publish a local, pending human-review pack."""
import copy
import hashlib
import html
import json
from pathlib import Path
import shutil

LAB = Path(__file__).resolve().parent
REPO = LAB.parent.parent
INPUTS = LAB/'outputs/frozen/inputs'
OUT = LAB/'outputs/frozen/results'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def main():
    manifest, records = read(OUT/'manifest.json'), read(OUT/'records.json')
    assert len(records) == 4 and len({r['id'] for r in records}) == 4
    assert manifest == read(INPUTS/'manifest.json')
    assert digest(INPUTS/'checks.json') == manifest['checks_sha256']
    assert read(INPUTS/'checks.json') == read(OUT/'checks.json')
    assert all(digest(REPO/p) == sha for p, sha in manifest['source_sha256'].items())
    inventory = Path('/mnt/c/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments/rapidocr-expanded-20261030/outputs/inventory.json')
    prior_paths = [inventory,
                   REPO/'experiments/rapidocr-shadow-20261031/outputs/20261030T165838Z/inputs/manifest.json',
                   REPO/'experiments/rapidocr-orientation-20261031/outputs/batch2/inputs/manifest.json']
    known = set()
    for path in prior_paths:
        value = read(path)
        docs = value if isinstance(value, list) else value['documents']
        known.update(d['sha256'] for d in docs)
    docs = {d['id']: d for d in manifest['documents']}
    for d in docs.values():
        assert d['sha256'] not in known
        assert digest(INPUTS/d['input']) == digest(Path(d['source_path'])) == d['sha256']
    assert all(digest(OUT/f'{r["id"]}-ocr.json') == r['ocr_sha256'] for r in records)
    runtime = read(OUT/'runtime.json')
    assert runtime['image_id'] == manifest['image']
    assert runtime['network_mode'] == 'none' and runtime['readonly_rootfs']
    assert {m['destination'] for m in runtime['mounts'] if m['rw']} == {'/out'}
    summary = {
        'real_documents': 4, 'selected_pages': 4, 'document_total_pages': sum(d['total_pages'] for d in docs.values()),
        'oriented': sum(r['status'] == 'oriented' for r in records),
        'unknown': sum(r['status'] == 'unknown' for r in records),
        'incorrect_accepted_orientation': sum(r['status'] == 'oriented' and r['correction_clockwise'] != 0 for r in records),
        'reference_checks_matched': sum(r['score']['matched'] for r in records),
        'reference_checks_total': sum(r['score']['total'] for r in records),
        'baseline_cases': sum(len(r['baseline_unchanged']) for r in records),
        'baseline_outputs_unchanged': all(all(r['baseline_unchanged'].values()) for r in records),
        'worker_seconds': round(sum(r['seconds'] for r in records), 3),
        'max_sampled_worker_tree_mib': max(r['peak_tree_mib'] for r in records),
        'frozen_files_unchanged': len(manifest['source_sha256']),
        'prior_unique_document_hashes': len(known), 'inputs_and_originals_unchanged': True,
        'human_review': 'pending', 'production_ingestion': False,
        'live_sandbox_version': 'unconfirmed', 'model_or_algorithm_changed': False,
    }
    save(OUT/'summary.json', summary)
    archived_records = copy.deepcopy(records)
    for r in archived_records:
        candidate = r.pop('normal_candidate') or {}
        r['normal_route_summary'] = {k: candidate.get(k) for k in ('source', 'status', 'needs_review', 'route_reason')}
        r['normal_issue_codes'] = [i.get('code') for i in candidate.get('issues', [])]
    evidence = {'summary': summary, 'manifest': manifest, 'records': archived_records, 'runtime': runtime,
                'novelty_sources_sha256': {str(p): digest(p) for p in prior_paths}}
    save(LAB/'evidence.json', evidence)
    save(LAB/'checks.json', read(OUT/'checks.json'))
    save(OUT/'review.json', {'reviewer': None, 'reviewed_at': None, 'production_ingestion': False,
                           'pages': [{'id': r['id'], 'page': r['page'], 'decision': 'pending',
                                      'orientation_correct': None, 'image_text_complete': None,
                                      'numbers_correct': None, 'table_association_correct': None,
                                      'notes': ''} for r in records]})
    sections, rows = [], []
    for r in records:
        key, d = r['id'], docs[r['id']]
        shutil.copyfile(INPUTS/f'{key}-p{r["page"]}.png', OUT/f'{key}-source.png')
        decision = read(OUT/f'{key}-ocr.json').get('decision', {})
        raw = next((c['raw'] for c in decision.get('candidates', []) if c['correction_clockwise'] == 0), {})
        text = '\n'.join(raw.get('lines', []))
        (OUT/f'{key}-reference.txt').write_text(text, encoding='utf8')
        baseline = (OUT/f'{key}-baseline-text.txt').read_text(encoding='utf8')
        rows.append(f'<tr><td><a href="#{key}">{key} · 第 {r["page"]} 页</a></td><td>{r["status"]}</td><td>{r["correction_clockwise"]}</td><td>{r["score"]["matched"]}/{r["score"]["total"]}</td><td>待人工复核</td></tr>')
        checks = ''.join('<tr><td>'+html.escape(c['id'])+'</td><td>'+html.escape(c['expected'])+'</td><td>'+html.escape(c['actual'])+'</td><td>'+str(c['matched'])+'</td></tr>' for c in r['score']['checks'])
        warning = ('方向未定：下方为原始 0° 候选，仅供人工比对，不能自动放行。' if r['status'] == 'unknown'
                   else '方向判断通过；数字准确性、表格关联与全文完整性仍需人工核对。')
        sections.append(f'<section id="{key}"><h2>{html.escape(d["name"])} · 第 {r["page"]} 页</h2><p>{warning}</p><p><a href="{key}-ocr.json">原始 OCR 与方向证据</a> · <a href="{key}-normal.json">正文路由与覆盖提示</a> · <a href="{key}-reference.txt">参考文字</a> · <a href="{key}-baseline-auto.txt">原 auto 输出</a> · <a href="{key}-baseline-image.txt">原 image 输出</a></p><div class="compare"><a href="{key}-source.png"><img src="{key}-source.png" alt="原页"></a><div><h3>现有 text 路径</h3><pre>{html.escape(baseline)}</pre></div><div><h3>0° OCR 候选（未人工批准）</h3><pre>{html.escape(text)}</pre></div></div><details><summary>预先冻结的核对项</summary><table><tr><th>项</th><th>原图转写</th><th>实际结果</th><th>匹配</th></tr>{checks}</table></details></section>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OCR 冻结验收与收敛</title><style>body{margin:24px;background:#f5f5f2;color:#242622;font:16px/1.6 system-ui}main{max-width:1800px;margin:auto}section{background:white;padding:24px;margin:28px 0;border:1px solid #d9dbd4}a{color:#245b72}.compare{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:20px}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui;max-height:1000px;overflow:auto}table{border-collapse:collapse;width:100%}th,td{padding:8px;border:1px solid #ccd4d9}details{margin-top:20px}summary{cursor:pointer}@media(max-width:950px){.compare{grid-template-columns:1fr}}@media print{pre{max-height:none}}</style><main><h1>OCR 冻结验收 · 本轮收敛</h1><p>4 份未见研报，各取 1 个图片内容页；未覆盖全部 21 页。沿用同一模型、方向算法和阈值，独立保存，未接入生产或正式入库。</p><p>核对项在 OCR 前冻结；匹配率只是局部文字检查，不是全文、表格结构或自动取数验收。unknown 的 0° 候选仅供人工参考。图表曲线含义不属于本轮文字识别范围。</p><p><a href="summary.json">摘要</a> · <a href="manifest.json">冻结记录</a> · <a href="review.json">人工复核记录模板</a></p><table><tr><th>页</th><th>方向状态</th><th>校正角度</th><th>参考检查</th><th>人工状态</th></tr>'''+''.join(rows)+'</table>'+''.join(sections)+'</main></html>'
    (OUT/'review.html').write_text(page, encoding='utf8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
