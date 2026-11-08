import sys,json
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from dotenv import load_dotenv
load_dotenv('.env')
import psycopg
from plugins.corpus.service import dsn
with psycopg.connect(dsn()) as c:
 c.execute('SET TRANSACTION READ ONLY')
 for schema,table in [('corpus','corpus_sources'),('corpus','corpus_jobs'),('corpus','corpus_publications'),('public','documents')]:
  print(schema,table,c.execute('SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position',(schema,table)).fetchall())
 print('generations',c.execute('SELECT generation,count(*),min(activated_at),max(activated_at) FROM corpus.corpus_publications GROUP BY generation').fetchall())
