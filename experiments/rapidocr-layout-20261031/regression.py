"""Recheck the original 26 pages using archived recognition, not new inference."""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

from validate import digest, write


def main():
    repo, archive, out = Path('/repo'), Path('/archive'), Path('/out')
    sys.path.insert(0, str(repo / 'experiments/rapidocr-body-20261030'))
    from body_reader import read_page
    from native_adapter import read_native
    expanded = archive / 'rapidocr-expanded-20261030'
    items = json.loads((expanded / 'manifest.json').read_text())
    references = json.loads((expanded / 'outputs/reference-effective.json').read_text())['pages']
    previous = {x['id']: x for x in json.loads(
        (archive / 'rapidocr-poppler-20261030/outputs/evaluation.json').read_text())}
    raws = {x['id']: x['result'] for x in json.loads((expanded / 'outputs/results.json').read_text())}
    tree = ast.parse((archive / 'ocr-smoke-20261019/evaluate_real.py').read_text())
    ns = {'re': re}
    exec(compile(ast.Module(body=[x for x in tree.body if isinstance(x, ast.FunctionDef)],
                           type_ignores=[]), '<frozen metric>', 'exec'), ns)
    norm, distance = ns['norm'], ns['excerpt_distance']

    def score(text, ref):
        return {'chars': sum(len(norm(x)) for x in ref['excerpts']),
                'edits': sum(distance(norm(x), norm(text))[0] for x in ref['excerpts']),
                'missing_keys': [x for x in ref['keys'] if norm(x) not in norm(text)]}

    rows = []
    hashes = {}
    for item in items:
        key, page = item['id'], item['page']
        path = expanded / 'samples' / Path(item['path']).name
        hashes[str(path)] = digest(path)
        assert hashes[str(path)] == item['sha256']
        native = read_native(path, page)
        baseline = {}
        for mode in ('auto', 'text', 'image'):
            cmd = [sys.executable, str(repo / 'plugins/tools/_doc_reader.py'), str(path),
                   '200000', '-', '0', mode, str(page)]
            baseline[mode] = subprocess.run(cmd, capture_output=True, timeout=120, check=True).stdout
        fixed = read_page(str(path), page, enabled=True, native_reader=lambda *_: native,
                          ocr_reader=lambda *_: raws[key])
        ordered = read_page(str(path), page, enabled=True, native_reader=lambda *_: '',
                            ocr_reader=lambda *_: raws[key])
        identical = True
        for mode in ('auto', 'text', 'image'):
            cmd = [sys.executable, str(repo / 'plugins/tools/_doc_reader.py'), str(path),
                   '200000', '-', '0', mode, str(page)]
            identical &= baseline[mode] == subprocess.run(cmd, capture_output=True, timeout=120, check=True).stdout
        row = {'id': key, 'source': fixed['source'], 'status': fixed['status'],
               'old': {k: previous[key]['hybrid'][k] for k in ('edits', 'chars', 'missing_keys')},
               'fixed': score(fixed['text'], references[key]),
               'ordered_ocr': score(ordered['text'], references[key]),
               'production_outputs_unchanged': identical,
               'coverage_note': 'No fresh detection on these 26 regression pages; native coverage remains unknown.'}
        rows.append(row)
        write(out / f'pages/{key}.json', {'native': native, 'fixed': fixed, 'ordered_ocr': ordered})
        write(out / 'scores.json', rows)
        print(json.dumps(row), flush=True)
    checks = {'pages': len(rows), 'baseline_cases': len(rows) * 3,
              'production_outputs_unchanged': all(x['production_outputs_unchanged'] for x in rows),
              'sources_unchanged': hashes == {p: digest(Path(p)) for p in hashes},
              'old_edits': sum(x['old']['edits'] for x in rows),
              'fixed_edits': sum(x['fixed']['edits'] for x in rows),
              'chars': sum(x['fixed']['chars'] for x in rows),
              'worse_pages': [x['id'] for x in rows if x['fixed']['edits'] > x['old']['edits']],
              'scope': 'Historical OCR replay and fresh Poppler coordinates; not throughput or deployment acceptance.'}
    write(out / 'checks.json', checks)
    print(json.dumps(checks), flush=True)
    assert checks['production_outputs_unchanged'] and checks['sources_unchanged']


if __name__ == '__main__':
    main()
