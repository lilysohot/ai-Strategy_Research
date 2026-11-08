import os,sys,uuid,subprocess
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from dotenv import load_dotenv
load_dotenv('.env')
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from plugins.corpus.service import dsn
name='vector_pilot_ingestion_'+uuid.uuid4().hex[:12]
base=dsn()
with psycopg.connect(base,autocommit=True) as conn:
 conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
 try:
  env=dict(os.environ,CORPUS_INGESTION_TEST_DSN=make_conninfo(base,dbname=name))
  result=subprocess.run(['uv','run','pytest','tests/test_corpus_ingestion_pg.py','-q'],env=env)
 finally:
  assert name.startswith('vector_pilot_ingestion_')
  conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
sys.exit(result.returncode)
