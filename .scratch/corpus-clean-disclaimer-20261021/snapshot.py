"""Freeze current clean outcomes and validated parse checkpoints; read-only PG."""
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from plugins.corpus.preparation.clean import clean_reader_result
from plugins.corpus.preparation.engine import _validate_parse_checkpoint
from plugins.corpus.retrieval.embedding import VectorConfig
from plugins.corpus.retrieval.index_pg import VectorIndex
from common import restore

spec = importlib.util.spec_from_file_location('acceptance', ROOT/'.scratch/corpus-vector-acceptance-20261020/run_eval.py')
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
_, dsn, digest, profile = prior.setup()
with VectorIndex(dsn, VectorConfig.from_env()).connect() as conn:
    rows = conn.execute('SELECT p.source_id, p.active_build_id, c.checkpoint FROM corpus.corpus_publications p JOIN corpus.corpus_source_checkpoints c ON c.source_id=p.source_id AND c.stage=%s WHERE p.active_build_id IS NOT NULL ORDER BY p.source_id', ('parse',)).fetchall()
assert len(rows) == 18
snapshot = []
for sid, build, checkpoint in rows:
    if isinstance(checkpoint, dict):
        checkpoint = json.dumps(checkpoint, ensure_ascii=False)
    data = json.loads(checkpoint)
    reader = restore(checkpoint, sid)
    clean = clean_reader_result(reader)
    assert clean.clean_rev == 'clean-5'
    snapshot.append({'source_id':sid, 'build_id':build, 'checkpoint':checkpoint,
                     'clean':asdict(clean)})
    for i,u in enumerate(reader.units):
        if ('特别声明' in u.raw_text or '法律声明' in u.raw_text) and len(u.raw_text)<200:
            print(sid[:8], u.ordinal, u.kind, repr(u.raw_text), flush=True)
            for next_u in reader.units[i+1:i+4]:
                print(' next', next_u.ordinal, next_u.kind, repr(next_u.raw_text[:100]))
path=HERE/'baseline.json'
assert not path.exists(), 'baseline must not be overwritten'
path.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
