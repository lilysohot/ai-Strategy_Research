"""Bounded acceptance run; never changes orientation decisions using ground truth."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def main():
    sys.path[:0] = ['/helpers', '/eval']
    from lab import measured
    from experiment import evaluate
    inputs, out = Path('/inputs'), Path('/out')
    manifest = json.loads((inputs/'manifest.json').read_text())
    checks = json.loads((inputs/'checks.json').read_text())
    if digest(inputs/'checks.json') != manifest['checks_sha256']:
        raise ValueError('Frozen checks changed')
    save(out/'manifest.json', manifest)
    save(out/'checks.json', checks)
    records = []
    for document in manifest['documents']:
        key, page = document['id'], document['pages'][0]
        pdf = inputs/document['input']
        if digest(pdf) != document['sha256']:
            raise ValueError('Frozen input changed')
        before = {}
        for mode in ('auto', 'text', 'image'):
            command = [sys.executable, '/reference/_doc_reader.py', str(pdf),
                       '200000', '-', '0', mode, str(page)]
            result = subprocess.run(command, check=True, capture_output=True, timeout=90)
            (out/f'{key}-baseline-{mode}.txt').write_bytes(result.stdout)
            before[mode] = hashlib.sha256(result.stdout).hexdigest()
        normal = measured([sys.executable, '/shadow/trial.py', 'page', '--pdf', str(pdf),
                           '--page', str(page)], timeout=90)
        save(out/f'{key}-normal.json', normal)
        result = measured([sys.executable, '/orientation/regression.py', 'worker',
                           '--pdf', str(pdf), '--page', str(page), '--rotation', '0'], timeout=90)
        save(out/f'{key}-ocr.json', result)
        decision = result.get('decision', {})
        reference = next((c['raw'] for c in decision.get('candidates', [])
                          if c['correction_clockwise'] == 0), None)
        # Diagnostic scoring does not promote an unknown decision to oriented.
        score = (evaluate({**reference, 'boxes_normalized_original': reference['boxes_normalized']},
                          checks[key]) if reference else
                 {'matched': 0, 'total': len(checks[key]), 'checks': []})
        equality = {}
        for mode, old_sha in before.items():
            command = [sys.executable, '/reference/_doc_reader.py', str(pdf),
                       '200000', '-', '0', mode, str(page)]
            comparison = subprocess.run(command, check=True, capture_output=True, timeout=90)
            equality[mode] = hashlib.sha256(comparison.stdout).hexdigest() == old_sha
        record = {'id': key, 'page': page, 'status': decision.get('status', result['status']),
                  'correction_clockwise': decision.get('correction_clockwise'),
                  'reason': decision.get('reason'), 'needs_review': decision.get('needs_review'),
                  'score_kind': 'zero_degree_candidate_for_manual_reference', 'score': score,
                  'baseline_unchanged': equality, 'baseline_sha256': before,
                  'seconds': result['wall_seconds'], 'peak_tree_mib': result['sampled_peak_tree_mib'],
                  'normal_status': normal.get('status'), 'normal_candidate': normal.get('candidate'),
                  'ocr_sha256': digest(out/f'{key}-ocr.json'), 'human_review': 'pending'}
        records.append(record)
        print(json.dumps({k: record[k] for k in ('id', 'status', 'correction_clockwise', 'seconds')}
                         | {'matched': score['matched'], 'total': score['total']}, ensure_ascii=False), flush=True)
    save(out/'records.json', records)


if __name__ == '__main__':
    main()
