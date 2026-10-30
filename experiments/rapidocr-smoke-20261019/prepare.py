import hashlib
import json
from pathlib import Path
import numpy as np
from rapidocr import RapidOCR
from config import params

for size in ('small', 'medium'):
    print('Preparing ' + size, flush=True)
    engine = RapidOCR(params=params(size))
    engine._load_cls_model()
    engine._load_rec_model()
    result = engine(np.full((100, 100, 3), 255, dtype=np.uint8))
    print(type(result), vars(result), flush=True)
    del engine
files = {str(p): {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
         for p in Path('/opt/ocr-models').rglob('*') if p.is_file()}
Path('/opt/model-manifest.json').write_text(json.dumps(files, indent=2))
