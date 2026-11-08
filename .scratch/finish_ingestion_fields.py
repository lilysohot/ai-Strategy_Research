from pathlib import Path
p=Path('plugins/corpus/preparation/search_pg.py');s=p.read_text().replace('    ingested_at: str | None = None\n','');s=s.replace('    source_coverage: int = 0\n','    source_coverage: int = 0\n    ingested_at: str | None = None\n');p.write_text(s)
p=Path('server/routes/corpus.py');s=p.read_text().replace('HTTP_422_UNPROCESSABLE_ENTITY','HTTP_422_UNPROCESSABLE_CONTENT');p.write_text(s)
