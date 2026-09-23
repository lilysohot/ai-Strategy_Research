from pathlib import Path
import shutil
r=Path('/home/administrator/FrontierAgent');out=r/'.scratch/m6-repair-20260923'
p=r/'tests/test_corpus_authority_pg.py';before=out/'before/tests/test_corpus_authority_pg.py';before.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,before)
