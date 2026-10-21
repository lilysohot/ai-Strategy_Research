"""Read-only inventory and PDF text inspection of the seven user-added sources."""
import hashlib
import json
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PREFIXES = (
    '2026-08-14_2026.08.14-中泰证券-',
    '2026-10-02_FundaAI_',
    '2026-10-19_研究_',
    '2026-10-21_研究',
    '2026-09-30_2026.09.30-',
    '2026-09-22_2026.09.22-',
    '2026-08-13_2026.08.13-goldman-sachs-',
)
files = sorted(p for p in (ROOT/'data/corpus').glob('*.pdf') if p.name.startswith(PREFIXES))
assert len(files) == 7
records = []
for path in files:
    sid = hashlib.sha256(path.read_bytes()).hexdigest()
    with fitz.open(path) as doc:
        texts = [page.get_text() for page in doc]
        row = dict(path=str(path), name=path.name, source_id=sid, bytes=path.stat().st_size,
                   pages=len(doc), page_text_chars=[len(t.strip()) for t in texts],
                   first_page=texts[0], last_page=texts[-1])
        doc[0].get_pixmap(matrix=fitz.Matrix(1,1)).save(str(HERE/f'{sid[:8]}-first.png'))
    records.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
(HERE/'inventory.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
