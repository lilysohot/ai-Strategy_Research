"""Freeze a six-page pilot from incoming reports; copy inputs, never ingest."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
PATTERNS = [
    ('now', '2026-10-29_财报点评_NOW_26Q3*.pdf'),
    ('ddog', '2026-10-28_前瞻_DDOG_3Q26*.pdf'),
    ('gemini', '2026-10-29_研报*Gemini_4_Carbon*.pdf'),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    import pymupdf
    incoming = REPO / 'data/corpus-incoming/20261026'
    archive = Path('/mnt/c/Users/Administrator/.codex/worktrees/5db5/FrontierAgent/experiments')
    inventory = json.loads((archive / 'rapidocr-expanded-20261030/outputs/inventory.json').read_text())
    known = {x['sha256'] for x in inventory}
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run = ROOT / 'outputs' / stamp
    run.mkdir(parents=True, exist_ok=False)
    inputs = run / 'inputs'
    inputs.mkdir()
    rows = []
    for key, pattern in PATTERNS:
        matches = list(incoming.glob(pattern))
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one report matching {pattern}')
        source = matches[0]
        sha = digest(source)
        if sha in known:
            raise ValueError('Pilot source belongs to historical 68-document OCR inventory')
        stats = []
        with pymupdf.open(source) as doc:
            for i, page in enumerate(doc):
                area = max(1, page.rect.width * page.rect.height)
                coverage = min(1, sum((pymupdf.Rect(x['bbox']) & page.rect).get_area()
                                      for x in page.get_image_info()) / area)
                stats.append({'page': i+1, 'native_chars': len(page.get_text().strip()),
                              'image_area_fraction': coverage})
        # Fixed before inference: first page plus largest image page; a text-only
        # report instead uses its middle page. This is partial coverage, not a
        # claim that the document was completely read.
        other = max(stats[1:], key=lambda x: (x['image_area_fraction'], -x['page']))
        if other['image_area_fraction'] == 0:
            other = stats[len(stats)//2]
        selected = sorted({1, other['page']})
        target = inputs / f'{key}.pdf'
        shutil.copyfile(source, target)
        assert digest(source) == digest(target) == sha
        rows.append({'id': key, 'name': source.name, 'source_path': str(source),
                     'sha256': sha, 'input': target.name, 'total_pages': len(stats),
                     'selected_pages': selected,
                     'not_processed_pages': [x['page'] for x in stats if x['page'] not in selected],
                     'selected_metadata': [x for x in stats if x['page'] in selected],
                     'novelty': 'Hash absent from historical 68-document OCR inventory; not a claim of unpublished database status.'})
    manifest = {'run_id': stamp, 'documents': rows, 'selected_page_count': sum(len(x['selected_pages']) for x in rows),
                'selection_policy': 'First page + greatest raster image area page; text-only reports use midpoint.',
                'human_review_required': True, 'production_ingestion': False}
    (inputs / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    code_paths = list((REPO / 'plugins/tools').glob('*.py')) + [
        REPO / 'experiments/rapidocr-body-20261030/body_reader.py',
        REPO / 'experiments/rapidocr-body-20261030/native_adapter.py',
        REPO / 'experiments/rapidocr-smoke-20261019/config.py',
    ]
    (run / 'code-before.json').write_text(json.dumps({str(p.relative_to(REPO)): digest(p)
                                                    for p in code_paths}, indent=2))
    print(json.dumps({'run': str(run), 'documents': [{k: r[k] for k in ('id','name','total_pages','selected_pages')}
                                                   for r in rows]}, ensure_ascii=False, indent=2))


def verify(run):
    run = Path(run).resolve()
    run.relative_to((ROOT / 'outputs').resolve())
    manifest = json.loads((run / 'inputs/manifest.json').read_text())
    before = json.loads((run / 'code-before.json').read_text())
    checks = {'sources_unchanged': all(digest(x['source_path']) == x['sha256'] for x in manifest['documents']),
              'input_copies_unchanged': all(digest(run / 'inputs' / x['input']) == x['sha256'] for x in manifest['documents']),
              'reader_code_unchanged': all(digest(REPO / p) == sha for p, sha in before.items()),
              'reader_files_checked': len(before), 'formal_database_mounted': False,
              'production_ingestion': False}
    (run / 'results/host-checks.json').write_text(json.dumps(checks, indent=2), encoding='utf8')
    print(json.dumps(checks))
    assert checks['sources_unchanged'] and checks['input_copies_unchanged'] and checks['reader_code_unchanged']


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--verify':
        verify(sys.argv[2])
    elif len(sys.argv) == 1:
        main()
    else:
        raise SystemExit('Usage: stage.py [--verify RUN_DIRECTORY]')
