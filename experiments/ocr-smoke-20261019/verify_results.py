"""Validate saved experiment evidence; never import or edit production modules."""
import json
from pathlib import Path

out = Path(__file__).parent / 'outputs'
checks = json.loads((out / 'checks.json').read_text(encoding='utf8'))
results = json.loads((out / 'results.json').read_text(encoding='utf8'))
assert checks['baseline_outputs_equal']
assert checks['baseline_case_count'] >= 6
assert checks['baseline_has_pymupdf'] == 'False'
assert checks['inputs_unchanged']
assert checks['worker_processes_remaining'] == '[]'
assert checks['timeout_after_ocr_started']
for probe, expected in [('blank_page', 'empty'), ('missing_language', 'error'),
                        ('damaged_pdf', 'error'), ('forced_timeout', 'timeout')]:
    assert checks['probes'][probe]['status'] == expected
assert all(run['status'] == 'ok' for row in results for run in row['runs'])
for phase in ['before', 'after']:
    native = (out / f'baseline-{phase}-control-native-auto.txt').read_text(encoding='utf8')
    assert '中文识别测试' in native and 'FA-2026-1019' in native
    scan = (out / f'baseline-{phase}-control-scan-auto.txt').read_text(encoding='utf8')
    assert 'not read: scanned image' in scan and 'FA-2026-1019' not in scan
    deep = (out / f'baseline-{phase}-control-scan-image.txt').read_text(encoding='utf8')
    assert 'OCR endpoint not configured' in deep
    assert 'FA-2026-1019' not in deep
for row in results:
    if row['sample'] == 'control-scan':
        assert row['repeat_text_identical']
        for expected in ['2026', '2026', '1019', '125', '3,750.50', '20261019', '125', '3750.50']:
            assert expected in row['digits'], (row['engine'], expected)
verification = {'passed': True, 'scope': 'synthetic controls only; real user PDFs pending',
                'native_content_checked': True, 'scan_did_not_auto_enable_ocr': True,
                'forced_ocr_timeout_reaped': True, 'scan_key_numbers_preserved': True}
(out / 'verification.json').write_text(json.dumps(verification, indent=2), encoding='utf8')
print(json.dumps(verification))
