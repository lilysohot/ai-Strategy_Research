"""One exploratory 150-DPI run per input/backend; not a repeated benchmark."""
import json
from pathlib import Path
import pymupdf
from lab import command, measured, write_json

root = Path('/lab')
out = root / 'outputs' / 'real-samples'
rows = []
for name in ['user1', 'user2']:
    path = root / 'samples' / f'{name}.pdf'
    with pymupdf.open(path) as doc:
        details = [{'width': im['width'], 'height': im['height'],
                    'xres': im['xres'], 'yres': im['yres'], 'bbox': list(im['bbox'])}
                   for im in doc[0].get_image_info()]
    for engine in ['pymupdf', 'cli']:
        cmd = command(path, 1, engine) + ['--dpi', '150']
        result = measured(cmd)
        rows.append({'sample': name, 'engine': engine, 'dpi': 150,
                     'source_images': details, **result})
        (out / f'{name}-p1-{engine}-150dpi.txt').write_text(result['text'], encoding='utf8')
        print(f"{name} {engine} 150 DPI: {result['status']} {result['wall_seconds']}s", flush=True)
write_json(out / 'dpi-probe.json', rows)
