"""Freeze clean-6 without changing any DB or previous audit artifacts."""
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / '.scratch/corpus-clean-disclaimer-20261021')]
from common import restore
from plugins.corpus.preparation.clean import CLEAN_REV, clean_reader_result

assert CLEAN_REV == 'clean-6'
assert not (HERE / 'baseline.json').exists()
base = json.loads((ROOT / '.scratch/corpus-clean-disclaimer-20261021/baseline.json').read_text())
for source in base:
    source['clean'] = asdict(clean_reader_result(restore(source['checkpoint'], source['source_id'])))
(HERE / 'baseline.json').write_text(json.dumps(base,ensure_ascii=False,indent=2))
(HERE / 'clean-6.py.txt').write_bytes((ROOT / 'plugins/corpus/preparation/clean.py').read_bytes())
print('Frozen 18 clean-6 outputs')
