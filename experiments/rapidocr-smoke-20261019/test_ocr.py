"""Isolated OCR experiment; never imported by production code."""
import argparse
import ast
import hashlib
import importlib.metadata
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/lab')
OUT = ROOT / 'outputs'
sys.path.insert(0, '/previous')
import lab as old
old.OUT = OUT
old.PYTHON = '/opt/rapid/bin/python'


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def worker(pdf, size, page=1):
    import numpy as np
    import pymupdf
    from rapidocr import RapidOCR
    from config import params

    with pymupdf.open(pdf) as doc:
        p = doc[page - 1]
        if p.rect.width * p.rect.height * (300 / 72) ** 2 > 25_000_000:
            raise ValueError('page pixel budget exceeded')
        pix = p.get_pixmap(dpi=300, alpha=False, colorspace=pymupdf.csRGB)
        # RapidOCR expects OpenCV BGR arrays.
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)[:, :, ::-1].copy()
    t = time.perf_counter()
    engine = RapidOCR(params=params(size))
    init_seconds = time.perf_counter() - t
    print('OCR_STARTED', file=sys.stderr, flush=True)
    result = engine(img)
    texts = list(result.txts) if result.txts is not None else []
    scores = [float(x) for x in result.scores] if result.scores is not None else []
    boxes = result.boxes.tolist() if result.boxes is not None else []
    print(json.dumps({'status': 'ok' if texts else 'empty', 'text': '\n'.join(texts),
                      'lines': texts, 'scores': scores, 'boxes': boxes,
                      'render_pixels': [pix.width, pix.height], 'init_seconds': init_seconds,
                      'ocr_seconds': float(result.elapse), 'engine': size}, ensure_ascii=False))


def command(pdf, size, page=1):
    return [sys.executable, '/lab/test_ocr.py', 'worker', '--pdf', pdf,
            '--size', size, '--page', str(page)]


def run():
    manifest = [{'id': s, 'path': f'/previous/samples/{s}.pdf', 'pages': [1]} for s in ('user1', 'user2')]
    hashes = {m['id']: old.digest(m['path']) for m in manifest}
    before = old.baseline(manifest, 'before')
    write('environment.json', {
        'python': sys.version,
        'packages': {p: importlib.metadata.version(p) for p in ('rapidocr','onnxruntime','pymupdf','pypdf','numpy','opencv-python-headless')},
        'cpu_max': Path('/sys/fs/cgroup/cpu.max').read_text(),
        'memory_max': Path('/sys/fs/cgroup/memory.max').read_text(),
        'model_manifest': json.loads(Path('/opt/model-manifest.json').read_text()),
        'input_sha256': hashes,
        'settings': '300dpi RGB rendered then BGR; RapidOCR defaults except v6 small/medium, model directory, warning log, ONNX intra/inter threads=1. Default global max_side_len=2000, det limit_side_len=736 limit_type=min, text_score=0.5; no layout filtering, no visual LLM.',
        'measurement': '3 serial fresh processes per sample/model; wall includes imports, rasterization, model initialization and OCR; tree RSS sampled every20ms; no GPU; network disabled'
    })
    (OUT / 'requirements-resolved.txt').write_text(subprocess.check_output([sys.executable, '-m', 'pip', 'freeze']).decode())
    records = []
    for sample in manifest:
        for size in ('small', 'medium'):
            runs = []
            for repeat in range(3):
                saved = OUT / f"{sample['id']}-{size}-{repeat+1}.json"
                result = json.loads(saved.read_text()) if saved.exists() else old.measured(command(sample['path'], size), timeout=90)
                runs.append(result)
                write(f"{sample['id']}-{size}-{repeat+1}.json", result)
                print(json.dumps({'sample':sample['id'], 'size':size, 'repeat':repeat+1,
                                  **{k:result.get(k) for k in ('status','wall_seconds','sampled_peak_tree_mib')} }), flush=True)
                if result['status'] != 'ok':
                    break  # Do not spend three deadlines repeating the same failure.
            (OUT / f"{sample['id']}-{size}.txt").write_text(runs[0].get('text',''), encoding='utf8')
            records.append({'sample':sample['id'],'engine':size,'runs':runs,
                            'median_seconds':statistics.median(r['wall_seconds'] for r in runs),
                            'max_sampled_peak_mib':max(r['sampled_peak_tree_mib'] for r in runs),
                            'repeat_text_identical':len({r.get('text') for r in runs})==1})
            write('results.json', records)
    after = old.baseline(manifest, 'after')
    probes = {
        'blank': old.measured(command('/previous/samples/control.pdf','small',3),timeout=30),
        'damaged': old.measured(command('/previous/samples/damaged.pdf','small'),timeout=30),
        'forced_timeout': old.measured(command(manifest[0]['path'],'medium'),timeout=0.2)
    }
    import psutil
    remaining = [p.pid for p in psutil.process_iter(['cmdline']) if p.pid != __import__('os').getpid()
                 and 'worker' in (p.info['cmdline'] or []) and '/lab/test_ocr.py' in (p.info['cmdline'] or [])]
    checks = {'baseline_outputs_equal':before==after,'baseline_case_count':len(before),
              'inputs_unchanged':hashes=={m['id']:old.digest(m['path']) for m in manifest},
              'worker_processes_remaining':remaining,'probes':probes}
    write('checks.json',checks)
    assert checks['baseline_outputs_equal'] and checks['inputs_unchanged'] and not remaining
    assert probes['blank']['status']=='empty' and probes['damaged']['status']=='error' and probes['forced_timeout']['status']=='timeout'
    assert all(r['status'] in ('ok','timeout','error') for row in records for r in row['runs'])


def evaluate():
    # Reuse the fixed manual reference and exact prior metric without executing its script.
    source = ast.parse(Path('/previous/evaluate_real.py').read_text())
    functions = ast.Module(body=[n for n in source.body if isinstance(n,ast.FunctionDef)], type_ignores=[])
    namespace = {'re': __import__('re')}
    exec(compile(functions,'prior_metric','exec'), namespace)
    norm, distance = namespace['norm'], namespace['excerpt_distance']
    manual = json.loads(Path('/previous/manual-checks.json').read_text())
    all_rows = []
    sources = [('rapidocr',OUT/'results.json'),('tesseract',Path('/previous/outputs/real-samples/results.json'))]
    for family,path in sources:
        for row in json.loads(path.read_text()):
            if row['runs'][0]['status'] != 'ok':
                all_rows.append({'family':family,'sample':row['sample'],'engine':row['engine'],
                                 'status':row['runs'][0]['status'], 'median_seconds':row['median_seconds'],
                                 'max_sampled_peak_mib':row['max_sampled_peak_mib']})
                continue
            spec = manual[row['sample']]
            text = norm(row['runs'][0].get('text',''))
            excerpts = []
            for i,ref in enumerate(spec['excerpts']):
                error,match = distance(norm(ref),text)
                excerpts.append({'reference':ref,'matched':match,'edits':error,'chars':len(norm(ref)),
                                 'body':i != (1 if row['sample']=='user1' else 0)})
            body = [x for x in excerpts if x['body']]
            keys = spec['key_tokens']
            missing = [k for k in keys if norm(k) not in text]
            body_keys = [k for k in keys if k!='+4.80%']
            all_rows.append({'family':family,'sample':row['sample'],'engine':row['engine'],
                'excerpt_cer':sum(x['edits'] for x in excerpts)/sum(x['chars'] for x in excerpts),
                'body_cer':sum(x['edits'] for x in body)/sum(x['chars'] for x in body),
                'body_chars':sum(x['chars'] for x in body), 'body_edits':sum(x['edits'] for x in body),
                'key_total':len(keys),'missing_keys':missing,
                'body_key_total':len(body_keys),'missing_body_keys':[k for k in body_keys if norm(k) not in text],
                'median_seconds':row['median_seconds'],'max_sampled_peak_mib':row['max_sampled_peak_mib'],
                'repeat_text_identical':row['repeat_text_identical'],'excerpts':excerpts})
    write('evaluation.json',{'method':manual['method'],
          'notes':'Best-span excerpt edit distance; not full document accuracy. Body subset excludes user1 subtitle and user2 title. Body key subset excludes stock quote +4.80%; key presence anywhere does not prove contextual correctness. Tesseract timings are historical same 2CPU/4GiB cap, not simultaneous benchmarking.',
          'evaluations':all_rows})
    for row in all_rows:
        print(json.dumps({k:v for k,v in row.items() if k!='excerpts'},ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['run','worker','evaluate'])
    parser.add_argument('--pdf')
    parser.add_argument('--size',choices=['small','medium'])
    parser.add_argument('--page',type=int,default=1)
    args = parser.parse_args()
    if args.action=='worker': worker(args.pdf,args.size,args.page)
    elif args.action=='run': run()
    else: evaluate()
