"""Create a new pilot database; never drop or overwrite any database."""
import hashlib
import subprocess
import psycopg
from psycopg import sql
from common import *

dump=HERE/'baseline.dump'
assert not (HERE/'clone.json').exists()
with psycopg.connect(connection('postgres'),autocommit=True) as conn:
    assert conn.execute('SELECT current_database()').fetchone()[0]=='postgres'
    assert not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(NEW,)).fetchone(),'target already exists'
with dump.open('wb') as out:
    subprocess.run(['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on','pg',
        'pg_dump','-U','postgres','-d',OLD,'-Fc','--no-owner','--no-privileges'],stdout=out,stderr=subprocess.PIPE,check=True)
with psycopg.connect(connection('postgres'),autocommit=True) as conn:
    conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(NEW)))
with dump.open('rb') as inp,(HERE/'restore.log').open('wb') as out:
    subprocess.run(['docker','exec','-i','pg','pg_restore','-U','postgres','-d',NEW,
        '--no-owner','--no-privileges','--exit-on-error'],stdin=inp,stdout=out,stderr=subprocess.STDOUT,check=True)
with psycopg.connect(connection(NEW)) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    assert publications(conn)==read('old-publications.json')
save('clone.json',{'from':OLD,'to':NEW,'dump_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),
    'dump_bytes':dump.stat().st_size,'publications_equal':True})
print('Cloned publication history, reviews, metadata and vector cache to '+NEW)
