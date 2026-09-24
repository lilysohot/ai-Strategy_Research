"""Replay the read-only default product gate with current code and separate outputs."""
from pathlib import Path
import hashlib
import json

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
original = ROOT / '.scratch/m7-fix-20260924/live_default_product.py'
source = original.read_text()
needle = 'OUT = Path(__file__).resolve().parent'
assert source.count(needle) == 1
source = source.replace(needle, 'OUT = ROOT / ".scratch/m8-review-20260924"')
(OUT / 'live-runner-manifest.json').write_text(json.dumps({
    'original': str(original.relative_to(ROOT)),
    'sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
    'adapter': 'Only OUT is redirected. PGOPTIONS read-only and zero-model trap retained.'}, indent=2))
exec(compile(source, str(original), 'exec'), {'__name__': '__main__', '__file__': str(original)})
