"""Isolated coordinate/coverage regression; no ingestion or production writes.

Uses frozen historical OCR for quality comparisons and fresh small-model raster
text DETECTION for coverage. These timings are not end-to-end OCR timings.
"""
import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def detect(path, page, prior):
    import numpy as np
    import pymupdf
    from rapidocr import RapidOCR
    sys.path.insert(0, str(prior / 'rapidocr-smoke-20261019'))
    from config import params
    with pymupdf.open(path) as doc:
        pg = doc[page - 1]
        if pg.rect.width * pg.rect.height * (300 / 72) ** 2 > 25_000_000:
            raise ValueError('page pixel budget exceeded')
        pix = pg.get_pixmap(dpi=300, alpha=False, colorspace=pymupdf.csRGB)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)[:, :, ::-1].copy()
    engine = RapidOCR(params=params('small'))
    result = engine(img, use_det=True, use_cls=False, use_rec=False)
    rects = []
    for box in result.boxes if result.boxes is not None else []:
        rects.append([float(box[:, 0].min()) / pix.width, float(box[:, 1].min()) / pix.height,
                      float(box[:, 0].max()) / pix.width, float(box[:, 1].max()) / pix.height])
    print(json.dumps({'status': 'ok', 'source': 'raster_text_detection', 'rects': rects,
                      'render_pixels': [pix.width, pix.height], 'dpi': 300,
                      'model': 'unchanged PP-OCRv6 small', 'recognition': False}))


def run(prior, repo, out):
    sys.path.insert(0, str(repo / 'experiments/rapidocr-body-20261030'))
    from body_reader import read_page
    from native_adapter import read_native
    poppler = prior / 'rapidocr-poppler-20261030'
    items = json.loads((poppler / 'manifest.json').read_text())
    refs = json.loads((poppler / 'outputs/reference-effective.json').read_text())['pages']
    metric = ast.parse((prior / 'ocr-smoke-20261019/evaluate_real.py').read_text())
    ns = {'re': re}
    exec(compile(ast.Module(body=[n for n in metric.body if isinstance(n, ast.FunctionDef)],
                           type_ignores=[]), '<historical metric>', 'exec'), ns)
    norm, distance = ns['norm'], ns['excerpt_distance']

    def score(text, spec):
        return {'edits': sum(distance(norm(x), norm(text))[0] for x in spec['excerpts']),
                'chars': sum(len(norm(x)) for x in spec['excerpts']),
                'missing_keys': [x for x in spec['keys'] if norm(x) not in norm(text)]}

    def baseline():
        values = {}
        for item in items:
            path = poppler / 'samples' / Path(item['path']).name
            for mode in ('auto', 'text', 'image'):
                p = subprocess.run([sys.executable, str(repo / 'plugins/tools/_doc_reader.py'),
                                    str(path), '200000', '-', '0', mode, str(item['page'])],
                                   capture_output=True, timeout=120, check=True)
                values[f"{item['id']}-{mode}"] = hashlib.sha256(p.stdout).hexdigest()
        return values

    source_hashes = {x['id']: digest(poppler / 'samples' / Path(x['path']).name) for x in items}
    assert all(source_hashes[x['id']] == x['sha256'] for x in items)
    before = baseline()
    rows, probes = [], []
    historical = json.loads((poppler / 'outputs/partial-native-probes.json').read_text())
    for item in items:
        key, page = item['id'], item['page']
        path = poppler / 'samples' / Path(item['path']).name
        native = read_native(path, page)
        raw = json.loads((poppler / f'outputs/raw/{key}.json').read_text())
        saved_detection = out / f'detection/{key}.json'
        if saved_detection.exists():
            record = json.loads(saved_detection.read_text())
            assert record['source_sha256'] == source_hashes[key]
            assert record['worker_sha256'] == digest(Path(__file__))
            detection = record['result']
        else:
            start = time.perf_counter()
            p = subprocess.run([sys.executable, __file__, 'detect', '--prior', str(prior),
                                '--pdf', str(path), '--page', str(page)],
                               capture_output=True, text=True, timeout=90, check=True)
            detection = json.loads(p.stdout)
            record = {'source_sha256': source_hashes[key], 'worker_sha256': digest(Path(__file__)),
                      'wall_seconds': time.perf_counter() - start, 'result': detection}
            write(saved_detection, record)
        read = lambda n: read_page(str(path), page, enabled=True, native_reader=lambda *_: n,
                                  ocr_reader=lambda *_: raw, coverage_reader=lambda *_: detection)
        fixed = read(native)
        ordered = read_page(str(path), page, enabled=True, native_reader=lambda *_: '',
                            ocr_reader=lambda *_: raw)
        write(out / f'pages/{key}.json', {'native': native, 'fixed': fixed, 'ordered_ocr': ordered})
        (out / f'{key}.txt').write_text(fixed['text'], encoding='utf8')
        row = {'id': key, 'status': fixed['status'], 'source': fixed['source'],
               'issues': [x['code'] for x in fixed['issues']], 'coverage': fixed['coverage']['status'],
               'layout': fixed['layout'], 'native': score(native['text'], refs[key]),
               'fixed': score(fixed['text'], refs[key]), 'ordered_ocr': score(ordered['text'], refs[key]),
               'native_raw_preserved': fixed['native_text'] == native['text'],
               'line_records_preserved': sorted(x['id'] for x in fixed['lines']) == list(range(len(native['lines'])))
                   if fixed['source'] == 'native' else None}
        rows.append(row)
        # Replay the ORIGINAL string-only omissions exactly, without restoring
        # text from coordinate metadata behind the caller's back.
        for old in (x for x in historical if x['id'] == key):
            damaged = copy.deepcopy(native)
            raw_lines = damaged['text'].splitlines(keepends=True)
            eligible = [i for i, line in enumerate(raw_lines) if len(norm(line)) >= 35
                        and sum(c.isalpha() for c in line) > 20]
            count = max(1, round(len(eligible) * old['fraction_of_dense_lines_removed']))
            start = (len(eligible) - count) // 2
            dropped = set(eligible[start:start+count])
            assert ''.join(line for i, line in enumerate(raw_lines) if i in dropped) == old['removed_text']
            damaged['text'] = ''.join(line for i, line in enumerate(raw_lines) if i not in dropped)
            result = read(damaged)
            probes.append({'id': key, 'kind': 'historical_string_loss',
                           'fraction': old['fraction_of_dense_lines_removed'],
                           'detected': any(x['code'] == 'native_coordinate_mismatch' for x in result['issues']),
                           'raw_preserved': result['text'] == damaged['text'],
                           'status': result['status'], 'issues': [x['code'] for x in result['issues']]})
        # Stronger, additional probes remove native text AND its boxes together.
        # No string mismatch remains; only independent raster evidence can help.
        if key != 'd003-p04':
            eligible = [i for i, x in enumerate(native['lines']) if len(norm(x['text'])) >= 25
                        and sum(c.isalpha() for c in x['text']) >= 20]
            for fraction in (.25, .5):
                count = max(1, round(len(eligible) * fraction))
                start = (len(eligible) - count) // 2
                drop = set(eligible[start:start + count])
                damaged = copy.deepcopy(native)
                damaged['lines'] = [x for i, x in enumerate(native['lines']) if i not in drop]
                damaged['text'] = '\n'.join(x['text'] for x in damaged['lines'])
                result = read(damaged)
                original_missing = {x['id'] for x in fixed['coverage'].get('missing_regions', [])}
                new_missing = {x['id'] for x in result['coverage'].get('missing_regions', [])} - original_missing
                probes.append({'id': key, 'kind': 'text_and_boxes_loss', 'fraction': fraction,
                               'removed_lines': sorted(drop), 'new_missing_region_ids': sorted(new_missing),
                               'detected': bool(new_missing), 'status': result['status'],
                               'issues': [x['code'] for x in result['issues']]})
        print(json.dumps(row, ensure_ascii=False), flush=True)
        write(out / 'scores.json', rows)
        write(out / 'probes.json', probes)
    after = baseline()
    checks = {'baseline_cases': len(before), 'production_outputs_unchanged': before == after,
              'sources_unchanged': source_hashes == {
                  x['id']: digest(poppler / 'samples' / Path(x['path']).name) for x in items},
              'native_raw_preserved': all(x['native_raw_preserved'] for x in rows),
              'historical_cases': sum(x['kind'] == 'historical_string_loss' for x in probes),
              'historical_detected': sum(x['detected'] for x in probes if x['kind'] == 'historical_string_loss'),
              'spatial_cases': sum(x['kind'] == 'text_and_boxes_loss' for x in probes),
              'spatial_detected': sum(x['detected'] for x in probes if x['kind'] == 'text_and_boxes_loss'),
              'scope': 'Isolated reproduction, no live deployment verification or ingestion',
              'ready_for_unattended_use': False}
    write(out / 'checks.json', checks)
    write(out / 'baseline-hashes.json', {'before': before, 'after': after})
    write(out / 'environment.json', {
        'poppler': subprocess.check_output(['pdftotext', '-v'], stderr=subprocess.STDOUT).decode(),
        'python': sys.version, 'cpu_max': Path('/sys/fs/cgroup/cpu.max').read_text(),
        'memory_max': Path('/sys/fs/cgroup/memory.max').read_text(),
        'image_id': os.environ.get('EXPERIMENT_IMAGE_ID'), 'network': 'none',
        'model_manifest': json.loads(Path('/opt/model-manifest.json').read_text()),
        'timing_scope': 'Fresh raster detection only; recognition replayed from historical cache.'})
    print(json.dumps(checks), flush=True)
    assert checks['production_outputs_unchanged'] and checks['sources_unchanged']
    assert checks['historical_cases'] == checks['historical_detected'] == 14
    assert checks['spatial_cases'] == checks['spatial_detected'] == 14


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['run', 'detect'])
    parser.add_argument('--prior', type=Path, default=Path('/archive'))
    parser.add_argument('--repo', type=Path, default=Path('/repo'))
    parser.add_argument('--out', type=Path, default=Path('/out'))
    parser.add_argument('--pdf')
    parser.add_argument('--page', type=int)
    args = parser.parse_args()
    if args.action == 'detect':
        detect(args.pdf, args.page, args.prior)
    else:
        run(args.prior, args.repo, args.out)
