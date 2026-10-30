"""ISOLATED EXPERIMENT. Never imported by FrontierAgent; no production integration."""
import argparse
import ast
import hashlib
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path('/lab')
OUT = ROOT / 'outputs' / os.environ.get('OCR_LAB_RUN', '')
DATA = Path('/usr/share/tesseract-ocr/5/tessdata')
PYTHON = '/opt/candidate/bin/python'
BASELINE = '/opt/baseline/bin/python'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fixture():
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    samples = ROOT / 'samples'
    samples.mkdir(exist_ok=True)
    lines = [
        'OCR isolated control sample 2026',
        'Order number: FA-2026-1019',
        'Quantity: 125 units. Total: 3,750.50 CNY.',
        '中文识别测试：这是用于验证的扫描页面。',
        '项目编号：20261019，数量：125，总计：3750.50 元。',
        '原始文件保持不变，识别结果另存。',
    ]
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    c = canvas.Canvas(str(samples / 'control.pdf'), pagesize=(595.28, 841.89))
    c.setFont('STSong-Light', 13)
    for i, text in enumerate(lines):
        c.drawString(40, 780 - i * 34, text)
    c.showPage()
    image = Image.new('RGB', (2480, 3508), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 54, index=2)
    for i, text in enumerate(lines):
        draw.text((165, 220 + i * 140), text, fill='black', font=font)
    image.save(samples / 'control-scan.png')
    c.drawImage(ImageReader(image), 0, 0, width=595.28, height=841.89)
    c.showPage()
    c.showPage()  # truly blank page, to distinguish empty from execution failure
    c.save()
    (samples / 'damaged.pdf').write_bytes(b'%PDF-1.7\nintentionally truncated fixture\n')
    write_json(samples / 'truth.json', {'2': '\n'.join(lines)})
    print('Created native-text, scanned and blank controls; original PDFs untouched.')


def worker(args):
    if args.engine == 'pymupdf':
        import pymupdf
        with pymupdf.open(args.pdf) as doc:
            page = doc[args.page - 1]
            pixels = page.rect.width * page.rect.height * (args.dpi / 72) ** 2
            if pixels > 25_000_000:
                raise ValueError('pixel budget exceeded before rasterization')
            print('OCR_STARTED', file=sys.stderr, flush=True)
            tp = page.get_textpage_ocr(language=args.lang, dpi=args.dpi, full=True,
                                       tessdata=args.tessdata)
            text = page.get_text('text', textpage=tp, sort=True)
            result = {'text': text, 'words': len(page.get_text('words', textpage=tp))}
    else:
        from pypdf import PdfReader
        box = PdfReader(args.pdf).pages[args.page - 1].mediabox
        if float(box.width) * float(box.height) * (args.dpi / 72) ** 2 > 25_000_000:
            raise ValueError('pixel budget exceeded before rasterization')
        with tempfile.TemporaryDirectory(prefix='ocr-page-') as temp:
            prefix = str(Path(temp) / 'page')
            subprocess.run(['pdftoppm', '-f', str(args.page), '-l', str(args.page),
                            '-r', str(args.dpi), '-singlefile', '-png',
                            args.pdf, prefix], check=True, capture_output=True)
            text = subprocess.check_output(['tesseract', prefix + '.png', 'stdout',
                                           '--tessdata-dir', args.tessdata,
                                           '-l', args.lang, '--psm', '3'], stderr=subprocess.PIPE).decode()
            result = {'text': text}
    result['status'] = 'ok' if result['text'].strip() else 'empty'
    print(json.dumps(result, ensure_ascii=False))


def measured(command, timeout=45):
    import psutil
    start = time.perf_counter()
    peak = 0
    killed = False
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        p = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        while p.poll() is None:
            try:
                root = psutil.Process(p.pid)
                members = [root] + root.children(recursive=True)
                rss = 0
                for member in members:
                    try:
                        rss += member.memory_info().rss
                    except psutil.Error:
                        pass
                peak = max(peak, rss)
            except psutil.Error:
                pass
            if time.perf_counter() - start > timeout:
                os.killpg(p.pid, signal.SIGKILL)
                killed = True
                break
            time.sleep(0.02)
        p.wait()
        elapsed = time.perf_counter() - start
        stdout.seek(0)
        stderr.seek(0)
        text = stdout.read().decode('utf8', 'replace')
        error = stderr.read().decode('utf8', 'replace')
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = {'text': text, 'status': 'error'}
    value.update(wall_seconds=round(elapsed, 3), sampled_peak_tree_mib=round(peak / 2**20, 1),
                 exit_code=p.returncode, timed_out=killed, stderr=error[-3000:])
    if killed:
        value['status'] = 'timeout'
    elif p.returncode:
        value['status'] = 'error'
    return value


def command(pdf, page, engine, lang='chi_sim+eng', tessdata=str(DATA)):
    return [PYTHON, str(ROOT / 'lab.py'), 'worker', '--pdf', str(pdf), '--page', str(page),
            '--engine', engine, '--lang', lang, '--tessdata', tessdata]


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def norm(text):
    return re.sub(r'\s+', '', text)


def baseline_bundle():
    source = Path('/reference/_doc_reader.py').read_text()
    tree = ast.parse(source)
    parts = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and any(
                     isinstance(t, ast.Name) and t.id == '_PARTS' for t in node.targets))
    return '\n\n'.join((Path('/reference') / p).read_text() for p in parts) + '\nmain()\n'


def baseline(manifest, phase):
    bundle = baseline_bundle()
    results = {}
    for item in manifest:
        for mode in ('auto', 'text', 'image'):
            key = f"{item['id']}-{mode}"
            # Explicit pages bypasses the production full-document cache.
            argv = [BASELINE if phase == 'before' else PYTHON, '-', item['path'],
                    '20000', '-', '0', mode, str(item['pages'][0])]
            env = {k: v for k, v in os.environ.items() if not k.startswith('READDOC_')}
            r = subprocess.run(argv, input=bundle, text=True, capture_output=True,
                               timeout=110, env=env)
            (OUT / f'baseline-{phase}-{key}.txt').write_text(r.stdout, encoding='utf8')
            results[key] = {'exit_code': r.returncode, 'stdout_sha256': hashlib.sha256(
                r.stdout.encode()).hexdigest(), 'stderr': r.stderr[-1000:]}
    write_json(OUT / f'baseline-{phase}.json', results)
    return results


def metadata():
    import importlib.metadata
    result = {'python': sys.version, 'platform': sys.platform,
              'packages': {p: importlib.metadata.version(p) for p in
                           ('pymupdf', 'pypdf', 'reportlab', 'pillow', 'psutil')},
              'language_data_sha256': {p.name: digest(p) for p in DATA.glob('*.traineddata')},
              'tesseract_cli': subprocess.check_output(['tesseract', '--version'], stderr=subprocess.STDOUT).decode(),
              'poppler': subprocess.check_output(['pdftoppm', '-v'], stderr=subprocess.STDOUT).decode(),
              'cpu_max': Path('/sys/fs/cgroup/cpu.max').read_text(),
              'memory_max': Path('/sys/fs/cgroup/memory.max').read_text(),
              'network_test': 'docker --network none; no cloud credentials mounted',
              'metrics': 'wall includes worker startup; RSS sums process tree, sampled every 20 ms; three serial fresh-worker repetitions'}
    write_json(OUT / 'environment.json', result)
    (OUT / 'requirements-resolved.txt').write_text(subprocess.check_output(
        [PYTHON, '-m', 'pip', 'freeze']).decode(), encoding='utf8')
    (OUT / 'debian-packages.tsv').write_text(subprocess.check_output(
        ['dpkg-query', '-W', '-f=${Package}\t${Version}\n']).decode(), encoding='utf8')


def run(manifest_file):
    OUT.mkdir(parents=True, exist_ok=True)
    metadata()
    manifest = json.loads(Path(manifest_file).read_text())
    hashes = {i['id']: digest(i['path']) for i in manifest}
    before = baseline(manifest, 'before')
    records = []
    for item in manifest:
        for page in item['pages']:
            for engine in ('pymupdf', 'cli'):
                runs = []
                for repeat in range(3):
                    result = measured(command(item['path'], page, engine))
                    runs.append(result)
                    print(f"{item['id']} p{page} {engine} #{repeat+1}: {result['status']} "
                          f"{result['wall_seconds']}s {result['sampled_peak_tree_mib']}MiB", flush=True)
                text = runs[0]['text']
                stem = f"{item['id']}-p{page}-{engine}"
                (OUT / (stem + '.txt')).write_text(text, encoding='utf8')
                record = {'sample': item['id'], 'page': page, 'engine': engine, 'runs': runs,
                          'median_seconds': statistics.median(r['wall_seconds'] for r in runs),
                          'max_sampled_peak_mib': max(r['sampled_peak_tree_mib'] for r in runs),
                          'text_chars': len(norm(text)), 'digits': re.findall(r'\d[\d,.]*', text),
                          'repeat_text_identical': len({r['text'] for r in runs}) == 1}
                truth = item.get('truth', {}).get(str(page))
                if truth:
                    record['whitespace_normalized_cer'] = distance(norm(truth), norm(text)) / len(norm(truth))
                records.append(record)
                write_json(OUT / 'results.json', records)
    after = baseline(manifest, 'after')
    checks = {'baseline_outputs_equal': before == after,
              'baseline_case_count': len(before),
              'inputs_unchanged': all(digest(i['path']) == hashes[i['id']] for i in manifest),
              'baseline_has_pymupdf': subprocess.check_output([BASELINE, '-c',
                  'import importlib.util; print(importlib.util.find_spec("pymupdf") is not None)']).decode().strip()}
    control = ROOT / 'samples/control.pdf'
    probes = {
        'blank_page': measured(command(control, 3, 'pymupdf')),
        'missing_language': measured(command(control, 2, 'pymupdf', lang='not_installed')),
        'damaged_pdf': measured(command(ROOT / 'samples/damaged.pdf', 1, 'pymupdf')),
        'forced_timeout': measured(command(control, 2, 'pymupdf'), timeout=0.5),
    }
    checks['probes'] = {k: {key: val for key, val in v.items() if key != 'text'} for k, v in probes.items()}
    checks['timeout_after_ocr_started'] = 'OCR_STARTED' in probes['forced_timeout']['stderr']
    checks['worker_processes_remaining'] = subprocess.check_output(
        [PYTHON, '-c', 'import psutil; print([p.pid for p in psutil.process_iter(["cmdline"]) '
         'if "worker" in (p.info["cmdline"] or []) and "/lab/lab.py" in (p.info["cmdline"] or [])])']).decode().strip()
    write_json(OUT / 'checks.json', checks)
    write_json(OUT / 'inputs-sha256.json', hashes)
    print(json.dumps(checks, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('fixture', 'worker', 'run'))
    parser.add_argument('--pdf')
    parser.add_argument('--page', type=int, default=1)
    parser.add_argument('--engine', choices=('pymupdf', 'cli'), default='pymupdf')
    parser.add_argument('--dpi', type=int, default=300)
    parser.add_argument('--lang', default='chi_sim+eng')
    parser.add_argument('--tessdata', default=str(DATA))
    parser.add_argument('--manifest', default='/lab/manifest.json')
    args = parser.parse_args()
    if args.action == 'fixture':
        fixture()
    elif args.action == 'worker':
        worker(args)
    else:
        run(args.manifest)
