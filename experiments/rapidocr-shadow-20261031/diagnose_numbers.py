"""Isolated, frozen-cell diagnosis; never correct or publish OCR automatically."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


def score(raw, fixture):
    width, height = raw['render_pixels']
    rows = []
    for cell in fixture['cells']:
        x0, y0, x1, y1 = cell['rect']
        hits = []
        for text, box, confidence in zip(raw['lines'], raw['boxes'], raw['scores']):
            cx = sum(p[0] for p in box) / len(box) / width
            cy = sum(p[1] for p in box) / len(box) / height
            if x0 <= cx < x1 and y0 <= cy < y1:
                hits.append({'text': text, 'confidence': confidence})
        actual = ''.join(h['text'] for h in hits).replace(' ', '')
        rows.append({'id': cell['id'], 'expected': cell['expected'], 'actual': actual,
                     'exact_match': actual == cell['expected'], 'hits': hits})
    return {'correct': sum(r['exact_match'] for r in rows), 'total': len(rows), 'cells': rows}


def run(args, fixture):
    import numpy as np
    import pymupdf
    from rapidocr import RapidOCR
    sys.path.insert(0, '/modelconfig')
    from config import params

    pdf = Path('/prior/inputs/ddog.pdf')
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != fixture['pdf_sha256']:
        raise ValueError('Frozen PDF hash changed')
    started = time.perf_counter()
    with pymupdf.open(pdf) as doc:
        pix = doc[6].get_pixmap(dpi=300, alpha=False, colorspace=pymupdf.csRGB)
    full = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    offset = (0, 0)
    image = full
    use_cls = args.mode != 'no-cls'
    if args.mode == 'table-crop':
        x0, y0, x1, y1 = fixture['table_rect']
        left, top, right, bottom = (round(x0*pix.width), round(y0*pix.height),
                                   round(x1*pix.width), round(y1*pix.height))
        image = full[top:bottom, left:right]
        offset = (left, top)
    engine = RapidOCR(params=params('small'))
    classification_trace = []
    if args.mode == 'trace-cls':
        original_cls = engine.cls_and_rotate
        original_rec = engine.recognize_txt

        def trace_cls(images):
            before = [im.copy() for im in images]
            rotated, classification = original_cls(images)
            for source, target, prediction in zip(before, rotated, classification.cls_res):
                classification_trace.append({
                    'angle': str(prediction[0]), 'confidence': float(prediction[1]),
                    'pixels_unchanged': bool(np.array_equal(source, target)),
                    'pixels_rotated_180': bool(np.array_equal(source[::-1, ::-1], target)),
                })
            return rotated, classification

        def trace_rec(images):
            recognized = original_rec(images)
            for item, text in zip(classification_trace, recognized.txts):
                item['recognized'] = text
            return recognized

        engine.cls_and_rotate = trace_cls
        engine.recognize_txt = trace_rec
    raw = {'lines': [], 'boxes': [], 'scores': [], 'render_pixels': [pix.width, pix.height]}
    result = engine(image[:, :, ::-1].copy(), use_det=True, use_cls=use_cls, use_rec=True)
    boxes = result.boxes.tolist() if result.boxes is not None else []
    raw.update(lines=list(result.txts) if result.txts is not None else [],
               scores=[float(s) for s in result.scores] if result.scores is not None else [],
               boxes=[[[p[0]+offset[0], p[1]+offset[1]] for p in b] for b in boxes])
    evidence = {'mode': args.mode, 'seconds': time.perf_counter()-started,
                'raw': raw, 'score': score(raw, fixture), 'human_review': 'pending',
                'production_ingestion': False, 'classification_trace': classification_trace}
    out = Path('/out') / (args.mode + '.json')
    with out.open('x', encoding='utf8') as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2)
    return evidence['score']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['replay','baseline','trace-cls','no-cls','table-crop'])
    parser.add_argument('--fixture', type=Path, default=Path(__file__).with_name('number-cells.json'))
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--assert-exact', action='store_true')
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding='utf8'))
    if args.mode == 'replay':
        candidate = json.loads(args.candidate.read_text(encoding='utf8'))
        result = score(candidate['engine_evidence']['ocr'], fixture)
    else:
        result = run(args, fixture)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if args.assert_exact and result['correct'] != result['total']:
        raise SystemExit(1)
