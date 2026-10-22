"""Read-only release inventory; never print credentials."""
import json
from pathlib import Path

import psycopg
from dotenv import load_dotenv, dotenv_values
from psycopg.conninfo import conninfo_to_dict, make_conninfo

load_dotenv()
from plugins.corpus.service import dsn

out = Path(__file__).parent
fields = conninfo_to_dict(dsn())
safe = {k: fields.get(k) for k in ('host', 'port', 'dbname')}
env = dotenv_values('.env')
safe['settings'] = {k: env.get(k) for k in (
    'CORPUS_TARGET_DB', 'CORPUS_READ_CHAIN', 'CORPUS_RETRIEVAL_MODE',
    'CORPUS_RETRIEVAL_RANKING', 'CORPUS_NATIVE_RETRIEVAL', 'CORPUS_NATIVE_TARGET_DB',
    'CORPUS_NATIVE_INDEX', 'CORPUS_VECTOR_TARGET_DB')}
safe['embedding_key_present'] = bool(env.get('CORPUS_VECTOR_API_KEY'))
inventory = {}
for label, db in [('production', fields.get('dbname')), ('pilot', 'vector_pilot_clean7_20261021')]:
    with psycopg.connect(make_conninfo('', **{**fields, 'dbname': db}), connect_timeout=10) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        inventory[label] = {
            'identity': conn.execute('SELECT current_database(),inet_server_addr()::text,inet_server_port()').fetchone(),
            'extensions': conn.execute('SELECT extname,extversion FROM pg_extension ORDER BY extname').fetchall(),
            'retrieval_tables': conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='corpus_retrieval' ORDER BY tablename").fetchall(),
            'publications': conn.execute('SELECT source_id,active_build_id,generation FROM corpus.corpus_publications ORDER BY source_id').fetchall(),
            'counts': conn.execute('SELECT (SELECT count(*) FROM corpus.corpus_sources),(SELECT count(*) FROM corpus.corpus_builds),(SELECT count(*) FROM corpus.corpus_chunks)').fetchone(),
            'sources': conn.execute('SELECT s.source_id,s.original_names,p.active_build_id FROM corpus.corpus_sources s JOIN corpus.corpus_publications p USING(source_id) ORDER BY s.source_id').fetchall(),
            'columns': conn.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='corpus' ORDER BY table_name,ordinal_position").fetchall(),
        }
report = {'connection': safe, 'inventory': inventory}
(out/'inventory.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'connection': safe, 'databases': {k: {a:b for a,b in v.items() if a not in ('columns','publications','sources')} for k,v in inventory.items()}, 'production_sources':inventory['production']['sources']}, ensure_ascii=False, indent=2))
