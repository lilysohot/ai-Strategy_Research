"""Score manually transcribed excerpts, not an invented full-document accuracy."""
import json
import re
from pathlib import Path

root = Path(__file__).parent
out = root / 'outputs' / 'real-samples'
manual = json.loads((root / 'manual-checks.json').read_text(encoding='utf8'))
records = json.loads((out / 'results.json').read_text(encoding='utf8'))
checks = json.loads((out / 'checks.json').read_text(encoding='utf8'))


def norm(text):
    return re.sub(r'\s+', '', text)


def excerpt_distance(reference, text):
    # Semi-global Levenshtein: full reference versus its best contiguous text span.
    previous = [0] * (len(text) + 1)
    starts = list(range(len(text) + 1))
    for i, char in enumerate(reference, 1):
        current, current_starts = [i], [0]
        for j, other in enumerate(text, 1):
            candidates = [(previous[j-1] + (char != other), starts[j-1]),
                          (previous[j] + 1, starts[j]),
                          (current[j-1] + 1, current_starts[j-1])]
            score, start = min(candidates, key=lambda p: p[0])
            current.append(score)
            current_starts.append(start)
        previous, starts = current, current_starts
    end = min(range(len(previous)), key=lambda j: previous[j])
    return previous[end], text[starts[end]:end]


evaluations = []
for row in records:
    spec = manual[row['sample']]
    text = norm(row['runs'][0]['text'])
    excerpts = []
    for reference in spec['excerpts']:
        reference = norm(reference)
        error, aligned = excerpt_distance(reference, text)
        excerpts.append({'reference': reference, 'aligned_ocr': aligned,
                         'edit_distance': error, 'reference_chars': len(reference)})
    errors = sum(e['edit_distance'] for e in excerpts)
    characters = sum(e['reference_chars'] for e in excerpts)
    missing = [t for t in spec['key_tokens'] if norm(t) not in text]
    evaluations.append({'sample': row['sample'], 'engine': row['engine'],
                        'excerpt_chars': characters, 'excerpt_edits': errors,
                        'excerpt_cer': errors / characters,
                        'excerpts': excerpts, 'key_tokens_total': len(spec['key_tokens']),
                        'key_tokens_present': len(spec['key_tokens']) - len(missing),
                        'missing_key_tokens': missing,
                        'median_seconds': row['median_seconds'],
                        'max_sampled_peak_mib': row['max_sampled_peak_mib'],
                        'repeat_text_identical': row['repeat_text_identical']})

assert checks['baseline_outputs_equal'] and checks['baseline_case_count'] == 6
assert checks['inputs_unchanged'] and checks['baseline_has_pymupdf'] == 'False'
assert checks['timeout_after_ocr_started'] and checks['worker_processes_remaining'] == '[]'
for name, expected in [('blank_page', 'empty'), ('missing_language', 'error'),
                       ('damaged_pdf', 'error'), ('forced_timeout', 'timeout')]:
    assert checks['probes'][name]['status'] == expected
for item in ['user1', 'user2']:
    for phase in ['before', 'after']:
        overview = (out / f'baseline-{phase}-{item}-auto.txt').read_text(encoding='utf8')
        deep = (out / f'baseline-{phase}-{item}-image.txt').read_text(encoding='utf8')
        assert 'not read: scanned image' in overview
        assert 'OCR endpoint not configured' in deep
assert all(run['status'] == 'ok' for row in records for run in row['runs'])
(out / 'manual-evaluation.json').write_text(json.dumps({
    'method': manual['method'], 'alignment': 'best contiguous span by semi-global edit distance',
    'isolation_behavior_checks_passed': True, 'evaluations': evaluations,
}, ensure_ascii=False, indent=2), encoding='utf8')
for row in evaluations:
    print(json.dumps({k: v for k, v in row.items() if k != 'excerpts'}, ensure_ascii=False))

probe_path = out / 'dpi-probe.json'
if probe_path.exists():
    probes = []
    for row in json.loads(probe_path.read_text(encoding='utf8')):
        spec = manual[row['sample']]
        text = norm(row['text'])
        errors = sum(excerpt_distance(norm(ref), text)[0] for ref in spec['excerpts'])
        chars = sum(len(norm(ref)) for ref in spec['excerpts'])
        missing = [t for t in spec['key_tokens'] if norm(t) not in text]
        probes.append({'sample': row['sample'], 'engine': row['engine'],
                       'dpi': row['dpi'], 'wall_seconds': row['wall_seconds'],
                       'sampled_peak_tree_mib': row['sampled_peak_tree_mib'],
                       'excerpt_cer': errors / chars, 'missing_key_tokens': missing})
    (out / 'dpi-evaluation.json').write_text(json.dumps(probes, ensure_ascii=False, indent=2), encoding='utf8')
    print('Exploratory DPI results: ' + json.dumps(probes, ensure_ascii=False))
