"""One-shot shadow trial. Fresh workers, bounded execution, separate evidence.

No database connector, production credentials, publishing or ingestion commands.
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def verify_inputs(manifest, inputs):
    total = 0
    ids = set()
    for doc in manifest['documents']:
        name = doc['input']
        if Path(name).name != name or name in ('.', '..'):
            raise ValueError('Input must be a direct child filename')
        path = inputs / name
        if path.resolve().parent != inputs.resolve():
            raise ValueError('Input escapes staged directory')
        if doc['id'] in ids or not doc['id'].isalnum():
            raise ValueError('Duplicate or unsafe document ID')
        ids.add(doc['id'])
        if digest(path) != doc['sha256']:
            raise ValueError('Input hash changed')
        pages = doc['selected_pages']
        if len(set(pages)) != len(pages) or any(type(p) is not int or not 1 <= p <= doc['total_pages'] for p in pages):
            raise ValueError('Invalid selected page range')
        total += len(pages)
    if not 1 <= total <= 6 or total != manifest['selected_page_count']:
        raise ValueError('Pilot is limited to six explicitly selected pages')


def page_worker(pdf, page):
    sys.path[:0] = ['/body', '/modelconfig']
    from body_reader import read_page
    from native_adapter import read_native
    from config import params
    import numpy as np
    import pymupdf
    from rapidocr import RapidOCR

    started = time.perf_counter()
    evidence = {}

    def infer(mode):
        with pymupdf.open(pdf) as doc:
            pg = doc[page-1]
            if pg.rect.width * pg.rect.height * (300/72)**2 > 25_000_000:
                raise ValueError('25MP pixel budget exceeded')
            pix = pg.get_pixmap(dpi=300, alpha=False, colorspace=pymupdf.csRGB)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)[:, :, ::-1].copy()
        engine = RapidOCR(params=params('small'))
        result = engine(img, use_det=True, use_cls=mode == 'ocr', use_rec=mode == 'ocr')
        boxes = result.boxes.tolist() if result.boxes is not None else []
        if mode == 'detect':
            rects = [[min(p[0] for p in b)/pix.width, min(p[1] for p in b)/pix.height,
                      max(p[0] for p in b)/pix.width, max(p[1] for p in b)/pix.height] for b in boxes]
            raw = {'status': 'ok', 'source': 'raster_text_detection', 'rects': rects,
                   'render_pixels': [pix.width, pix.height]}
        else:
            texts = list(result.txts) if result.txts is not None else []
            scores = [float(x) for x in result.scores] if result.scores is not None else []
            raw = {'status': 'ok' if texts else 'empty', 'text': '\n'.join(texts),
                   'lines': texts, 'scores': scores, 'boxes': boxes,
                   'render_pixels': [pix.width, pix.height]}
        evidence[mode] = raw
        return raw

    result = read_page(pdf, page, enabled=True, native_reader=read_native,
                       ocr_reader=lambda *_: infer('ocr'), coverage_reader=lambda *_: infer('detect'))
    print(json.dumps({'status': result['status'], 'candidate': result, 'engine_evidence': evidence,
                      'worker_body_seconds': time.perf_counter()-started}, ensure_ascii=False))


def pending_review(manifest, records):
    sources = {x['id']: x for x in manifest['documents']}
    return {'run_id': manifest['run_id'], 'reviewer': None, 'reviewed_at': None,
            'instructions': 'Compare source image, candidate, and baseline. Record omissions, numbers/units, order, and chart limits. Acceptance is for this experiment only, never ingestion.',
            'production_ingestion': False, 'pages': [
                {'id': r['id'], 'source_sha256': sources[r['document']]['sha256'],
                 'candidate_sha256': r['candidate_sha256'], 'decision': 'pending',
                 'body_complete': None, 'numbers_and_names_correct': None,
                 'reading_order_correct': None, 'visual_limits_clear': None,
                 'notes': ''} for r in records]}


def render_review(manifest, records, out):
    precheck = ''
    if (out / 'AGENT_PRECHECK.zh-CN.md').exists():
        precheck = '<p><a href="AGENT_PRECHECK.zh-CN.md">助手初查（不代替人工复核）</a>：DDOG 第 7 页存在小数点丢失等数字错误，请优先核验表格。其余原生页提示主要涉及页脚和品牌文字，正文仍待逐页检查。</p>'
    sections = []
    for r in records:
        key = r['id']
        folder = out / 'pages' / key
        native = (folder / 'baseline-text.txt').read_text(encoding='utf8')
        candidate = (folder / 'candidate.txt').read_text(encoding='utf8')
        flags = html.escape(json.dumps(r['issues'], ensure_ascii=False, indent=2))
        sections.append(f'''<section id="{key}"><h2>{html.escape(r['name'])} · 第 {r['page']} 页</h2>
<p><b>人工复核：待处理</b> · 路径 {r['source']} · 组件状态 {r['status']} · {r['seconds']:.2f} 秒</p>
<p><a href="pages/{key}/source.png">打开原页大图</a> · <a href="pages/{key}/marked.png">缺口标记图</a> ·
<a href="pages/{key}/candidate.json">完整识别与坐标证据</a> · <a href="pages/{key}/baseline-auto.txt">原 auto 输出</a> ·
<a href="pages/{key}/baseline-image.txt">原 image 输出</a></p>
<div class="compare"><a href="pages/{key}/source.png"><img src="pages/{key}/source.png" alt="原页"></a>
<div><h3>现有 text 路径</h3><pre>{html.escape(native)}</pre></div>
<div><h3>旁路候选</h3><pre>{html.escape(candidate)}</pre></div></div>
<details><summary>组件提示与缺口</summary><pre>{flags}</pre></details>
<p>请核对：段落遗漏 / 数字、公司名、单位 / 阅读顺序 / 图表仍未理解的内容。</p></section>''')
    navigation = ' · '.join(f'<a href="#{r["id"]}">{r["id"]}</a>' for r in records)
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>OCR 旁路试运行 · 人工复核</title>
<style>body{{margin:24px;background:#f5f5f2;color:#242622;font:16px/1.6 system-ui,sans-serif}}main{{max-width:1800px;margin:auto}}h1{{font-size:28px}}section{{background:white;padding:24px;margin:28px 0;border:1px solid #d9dbd4}}a{{color:#245b72}}.compare{{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:20px}}img{{width:100%;height:auto}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui,sans-serif;max-height:1050px;overflow:auto}}h3{{border-bottom:2px solid #bcc8bf}}@media(max-width:950px){{.compare{{grid-template-columns:1fr}}}}@media print{{pre{{max-height:none}}section{{break-before:page}}}}</style>
<main><h1>OCR 旁路试运行 · {html.escape(manifest['run_id'])}</h1>
<p>3 份研报 · 6 个选定页面。仅隔离环境对照，未覆盖全报告、未确认线上环境、未写正式库。</p>
<p>基线是当前 read_file 的 auto/text/image 代码路径；隔离容器不配置远程 OCR 或视觉端点。状态 ok 不代表人工通过。</p>
<p><a href="review.json">人工复核记录模板</a> · <a href="summary.json">运行摘要</a> · <a href="manifest.json">冻结输入和未处理页</a></p>
<p>全部页面保持待复核。可以直接把“页面编号＋问题/通过结论”反馈给助手登记；也可编辑 review.json，填写复核人、时间和结论。没有发布或入库按钮。</p>
{precheck}<nav>{navigation}</nav>{''.join(sections)}</main></html>'''
    (out / 'review.html').write_text(page, encoding='utf8')


def run():
    import pymupdf
    from PIL import Image, ImageDraw
    sys.path.insert(0, '/helpers')
    from lab import measured
    inputs, out = Path('/inputs'), Path('/out')
    manifest = json.loads((inputs / 'manifest.json').read_text())
    verify_inputs(manifest, inputs)
    write(out / 'manifest.json', manifest)
    records = []
    started = time.perf_counter()
    for doc in manifest['documents']:
        pdf = inputs / doc['input']
        for number in doc['selected_pages']:
            key = f'{doc["id"]}-p{number:02d}'
            folder = out / 'pages' / key
            folder.mkdir(parents=True, exist_ok=False)
            baseline_hashes = {}
            for mode in ('auto', 'text', 'image'):
                command = [sys.executable, '/reference/_doc_reader.py', str(pdf), '200000', '-', '0', mode, str(number)]
                p = subprocess.run(command, capture_output=True, text=True, timeout=120, check=True)
                path = folder / f'baseline-{mode}.txt'
                path.write_text(p.stdout, encoding='utf8')
                baseline_hashes[mode] = digest(path)
            with pymupdf.open(pdf) as source:
                source[number-1].get_pixmap(dpi=140, alpha=False).save(folder / 'source.png')
            measured_result = measured([sys.executable, __file__, 'page', '--pdf', str(pdf), '--page', str(number)], timeout=90)
            write(folder / 'candidate.json', measured_result)
            candidate = measured_result.get('candidate') or {'text': '', 'source': 'none', 'status': measured_result['status'],
                'issues': [{'code': 'worker_failed', 'message': 'No candidate returned; inspect worker evidence.'}]}
            (folder / 'candidate.txt').write_text(candidate['text'], encoding='utf8')
            im = Image.open(folder / 'source.png').convert('RGB')
            draw = ImageDraw.Draw(im)
            for gap in candidate.get('coverage', {}).get('missing_regions', []):
                x0,y0,x1,y1 = gap['rect']
                draw.rectangle((x0*im.width, y0*im.height, x1*im.width, y1*im.height), outline='red', width=3)
            im.save(folder / 'marked.png')
            after = {}
            for mode in ('auto', 'text', 'image'):
                p = subprocess.run([sys.executable, '/reference/_doc_reader.py', str(pdf), '200000', '-', '0', mode, str(number)],
                                   capture_output=True, text=True, timeout=120, check=True)
                after[mode] = hashlib.sha256(p.stdout.encode()).hexdigest()
            record = {'id': key, 'document': doc['id'], 'name': doc['name'], 'page': number,
                      'status': candidate['status'], 'source': candidate['source'],
                      'coverage': candidate.get('coverage', {}).get('status', 'not_checked'),
                      'issues': candidate['issues'], 'characters': len(candidate['text']),
                      'seconds': measured_result['wall_seconds'], 'peak_tree_mib': measured_result['sampled_peak_tree_mib'],
                      'timed_out': measured_result['timed_out'], 'worker_exit_code': measured_result['exit_code'],
                      'candidate_sha256': digest(folder / 'candidate.txt'),
                      'baseline_outputs_unchanged': baseline_hashes == after, 'human_review': 'pending'}
            records.append(record)
            write(out / 'records.json', records)
            write(out / 'review.json', pending_review(manifest, records))
            render_review(manifest, records, out)
            print(json.dumps({k: record[k] for k in ('id','source','status','characters','seconds','peak_tree_mib','baseline_outputs_unchanged')}, ensure_ascii=False), flush=True)
    verify_inputs(manifest, inputs)
    summary = {'run_id': manifest['run_id'], 'documents': len(manifest['documents']), 'pages': len(records),
               'baseline_cases': len(records)*3, 'baseline_outputs_unchanged': all(x['baseline_outputs_unchanged'] for x in records),
               'inputs_unchanged': True, 'human_review_pending': len(records), 'production_ingestion': False,
               'worker_seconds_total': sum(x['seconds'] for x in records),
               'max_sampled_worker_tree_mib': max(x['peak_tree_mib'] for x in records),
               'serial_batch_seconds': time.perf_counter()-started,
               'timing_scope': 'Fresh candidate subprocesses including imports, native extraction, rendering and detection/OCR; no cached inference. Batch also includes baselines and preview generation.',
               'image_id': os.environ['EXPERIMENT_IMAGE_ID'],
               'poppler': subprocess.check_output(['pdftotext','-v'], stderr=subprocess.STDOUT).decode(),
               'model_manifest': json.loads(Path('/opt/model-manifest.json').read_text()),
               'scope': 'Isolated code-path comparison, not live deployment or full-report acceptance.'}
    write(out / 'summary.json', summary)
    assert summary['baseline_outputs_unchanged']
    print(json.dumps({k:v for k,v in summary.items() if k != 'model_manifest'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['run', 'page'])
    parser.add_argument('--pdf')
    parser.add_argument('--page', type=int)
    args = parser.parse_args()
    if args.action == 'page':
        page_worker(args.pdf, args.page)
    else:
        run()
