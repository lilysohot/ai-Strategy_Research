"""Real PG lifecycle in one rollback-only transaction; no provider calls."""
import contextlib,copy,json,sys
from dataclasses import asdict
from unittest.mock import patch,Mock
from verify_tools import prior,native_live,native_pg,NativeIndex,OUT,HERE,save
import psycopg
from psycopg.types.json import Jsonb
from plugins.corpus.preparation.read_pg import IntegrityError,WithdrawnError
from plugins.corpus.retrieval.native_sync import sync
from plugins.corpus.retrieval.embedding import VectorConfig,EmbeddingResult,text_hash

class Cursor:
    def __init__(self,cur):self.cur=cur
    def __enter__(self):self.cur.__enter__();return self
    def __exit__(self,*args):return self.cur.__exit__(*args)
    def execute(self,sql,*args):
        # The outer test transaction already owns isolation. Every other SQL
        # statement, including savepoints and vector SQL, executes unmodified.
        if sql.startswith('SET TRANSACTION'):return None
        return self.cur.execute(sql,*args)
    def __getattr__(self,name):return getattr(self.cur,name)
class Borrow:
    def __init__(self,conn):self.conn=conn
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cursor(self,*args,**kwargs):return Cursor(self.conn.cursor(*args,**kwargs))
    def __getattr__(self,name):return getattr(self.conn,name)

def main():
    seed=NativeIndex(OUT/'manifest.json');cfg=VectorConfig.from_env()
    target=prior.batch.TARGET;dsn=prior.batch.TARGET_DSN
    before=prior.batch.publications(target)
    conn=psycopg.connect(dsn)
    stages={}
    try:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        with conn.cursor() as cur:
            initial=native_live.refresh_on(cur,seed)
            cur.execute('SELECT p.source_id,p.active_build_id,b.build_id FROM corpus.corpus_publications p JOIN corpus.corpus_builds b ON b.source_id=p.source_id WHERE p.source_id=ANY(%s::text[]) AND b.build_id<>p.active_build_id AND EXISTS(SELECT 1 FROM corpus.corpus_chunks c WHERE c.build_id=b.build_id) ORDER BY p.source_id,b.build_id LIMIT 1',(seed.manifest['source_allowlist'],))
            sid,old,alternate=cur.fetchone()
            old_block=next(b for b in native_pg._load_blocks(cur,initial).values() if b.source_id==sid)
            oldloc=native_live.locator_for(old_block.chunk_id,old_block.text,[asdict(s) for s in old_block.slices])
            cur.execute('UPDATE corpus.corpus_publications SET active_build_id=%s,generation=generation+1 WHERE source_id=%s',(alternate,sid))
            changed=native_live.refresh_on(cur,seed)
            assert not any(c['build_id']==old for c in changed.chunks)
            assert any(c['build_id']==alternate for c in changed.chunks)
            try:native_pg._snapshot(cur,initial)
            except IntegrityError:pass
            else:raise AssertionError('stale snapshot accepted')
            # Construct one new projected input on this alternate build. The
            # fixture mutates are rollback-only, not a bypass of publication.
            row=next(c for c in changed.chunks if c['build_id']==alternate)
            uid=row['unit_refs'][0];u=changed.units[alternate,uid]
            raw=u['raw_text']+'生命周期新增正文唯一标识。'
            cur.execute('UPDATE corpus.corpus_units SET raw_text=%s,content_hash=%s,clean_view=NULL WHERE build_id=%s AND unit_id=%s',(raw,text_hash(raw),alternate,uid))
            cur.execute('UPDATE corpus.corpus_chunks SET search_text=%s,unit_refs=%s,context_refs=%s WHERE build_id=%s AND chunk_id=%s',('生命周期新增正文唯一标识。',[uid],[],alternate,row['chunk_id']))
            changed=native_live.refresh_on(cur,seed)
            missing=sum(c['input_hash'] not in changed.vectors for c in changed.chunks)
            assert missing>0
            stages['publish_refresh']={'new_build_visible':True,'old_build_not_retrieved':True,'pending_chunks':missing}
        # A second real connection must see committed publications only.
        assert prior.batch.publications(target)==before
        with patch.object(native_live.psycopg,'connect',return_value=Borrow(conn)),patch.object(native_pg,'query_vector',side_effect=prior.vector):
            saved=native_live.fetch(dsn,target,'cv2:'+old,oldloc)
            assert saved.text==old_block.text and not saved.active
            stages['historical_handle']={'exact_text_retained':True,'active':saved.active}
            result=native_pg.search_native(dsn,target,prior.queries[0]['question'],changed,allow_fallback=True)
            assert result.retrieval_mode=='lexical' and result.fallback_reason=='native_vectors_pending'
            assert all(b.build_id!=old for b in result.blocks)
            conn.execute('DROP TABLE native_chunks,native_dates')
            stages['pending_fallback']={'mode':result.retrieval_mode,'reason':result.fallback_reason}
            vector=next(iter(seed.vectors.values()))['vector']
            embed=Mock(return_value=EmbeddingResult(tuple(vector),{}))
            synced=sync(dsn,target,seed,cfg,embed,max_requests=1000)
            assert synced['pending_chunks']==0
            synced2=sync(dsn,target,seed,cfg,embed,max_requests=1000)
            assert synced2['requests_this_run']==0
            live=native_live.refresh(dsn,target,seed)
            recovered=native_pg.search_native(dsn,target,prior.queries[0]['question'],live,allow_fallback=True)
            assert recovered.retrieval_mode=='hybrid' and recovered.fallback_reason is None
            conn.execute('DROP TABLE native_chunks,native_dates')
            stages['sync_and_recover']={'simulated_document_calls':embed.call_count,'first':synced,'repeat':synced2,'recovered':recovered.retrieval_mode}
            # Force a real SQL exception inside the vector savepoint.
            with patch.object(native_pg,'_DENSE_SQL','SELECT 1/0'):
                fallback=native_pg.search_native(dsn,target,prior.queries[0]['question'],live,allow_fallback=True)
            assert fallback.retrieval_mode=='lexical' and fallback.fallback_reason=='native_vector_query_failed'
            conn.execute('DROP TABLE native_chunks,native_dates')
            stages['vector_sql_failure']={'reason':fallback.fallback_reason,'transaction_usable':conn.execute('SELECT 1').fetchone()[0]==1}
            with conn.cursor() as cur:
                cur.execute('UPDATE corpus.corpus_admissions SET decision=%s WHERE decision_id=(SELECT current_decision_id FROM corpus.corpus_sources WHERE source_id=%s)',('excluded_by_policy',sid))
                removed=native_live.refresh_on(cur,seed)
                assert not any(c['source_id']==sid for c in removed.chunks)
                try:native_pg._snapshot(cur,live)
                except WithdrawnError:pass
                else:raise AssertionError('revoked source accepted')
            try:native_live.fetch(dsn,target,'cv2:'+old,oldloc)
            except WithdrawnError:pass
            else:raise AssertionError('revoked old handle served')
            stages['withdrawal']={'excluded_from_candidates':True,'old_handle_rejected':True}
    finally:
        conn.rollback();conn.close()
    stages['audit']={'all_fixture_mutations_rolled_back':prior.batch.publications(target)==before,'provider_calls':0,
                     'publication_generation_changes_committed':0,'lifecycle_uses_real_pg_with_borrowed_transaction':True}
    save('lifecycle.json',stages)
    print(json.dumps(stages,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
