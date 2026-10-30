import hashlib
import json
from pathlib import Path
import numpy as np
from rapidocr import RapidOCR
from config import params

engine = RapidOCR(params=params('small'))
engine._load_cls_model()
engine._load_rec_model()
engine(np.full((100,100,3),255,dtype=np.uint8))
files = {p.name: {'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
         for p in Path('/opt/ocr-models').rglob('*') if p.is_file()}
expected = {
    'PP-OCRv6_det_small.onnx':'090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
    'PP-OCRv6_rec_small.onnx':'6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884',
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx':'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c',
}
assert all(files[k]['sha256']==v for k,v in expected.items()), 'Model differs from prior experiment'
Path('/opt/model-manifest.json').write_text(json.dumps(files,indent=2))
print('All small model hashes match previous experiment',flush=True)
