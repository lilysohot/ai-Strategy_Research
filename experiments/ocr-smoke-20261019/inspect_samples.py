import json
import subprocess
from pathlib import Path

import pymupdf

root = Path('/lab')
results = []
for name in ['user1', 'user2']:
    path = root / 'samples' / f'{name}.pdf'
    with pymupdf.open(path) as doc:
        item = {'id': name, 'pages': len(doc), 'needs_password': doc.needs_pass, 'details': []}
        for index in range(min(len(doc), 12)):
            p = doc[index]
            text = p.get_text()
            page = {'page': index + 1, 'width': p.rect.width, 'height': p.rect.height,
                    'text_chars': len(text.strip()), 'images': len(p.get_images()),
                    'fonts': [f[3] for f in p.get_fonts()]}
            item['details'].append(page)
            (root / 'outputs' / f'{name}-p{index+1}-textlayer.txt').write_text(text, encoding='utf8')
            if index < 3:
                subprocess.run(['pdftoppm', '-f', str(index+1), '-l', str(index+1), '-r', '110',
                                '-singlefile', '-png', str(path),
                                str(root / 'outputs' / f'{name}-p{index+1}-preview')],
                               check=True, capture_output=True)
        results.append(item)
(root / 'outputs' / 'user-samples-inspection.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(results, ensure_ascii=False, indent=2))
