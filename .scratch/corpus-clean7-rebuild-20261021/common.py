import json
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
OLD='vector_pilot_corpus_20261020'
NEW='vector_pilot_clean7_20261021'
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from plugins.corpus.service import dsn
from plugins.corpus.retrieval.embedding import VectorConfig
load_dotenv(ROOT/'.env')
BASE=conninfo_to_dict(dsn())
CONFIG=VectorConfig.from_env()
assert CONFIG.input_variant=='published-search-text-v1'

def connection(db):
    assert db in (OLD,NEW,'postgres')
    return make_conninfo('',**{**BASE,'dbname':db})

def setup(db):
    assert db in (OLD,NEW)
    os.environ['CORPUS_TARGET_DB']=db
    os.environ['CORPUS_DSN']=connection(db)
    os.environ['CORPUS_VECTOR_TARGET_DB']=db
    os.environ['CORPUS_READ_CHAIN']='new'
    return replace(CONFIG,target_db=db,timeout=60)

def save(name,value):
    path=HERE/name
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str))
    tmp.replace(path)

def read(name):
    return json.loads((HERE/name).read_text())

def publications(conn):
    return [list(r) for r in conn.execute('SELECT source_id,active_build_id,generation FROM corpus.corpus_publications ORDER BY source_id').fetchall()]
