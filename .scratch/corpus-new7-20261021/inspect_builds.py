from run_batch import *
with PgStore(TARGET_DSN,sandbox_db=TARGET) as store:
    for row in load('build-results.json'):
        if not row.get('build_id'): continue
        build=store.get_build(row['build_id'])
        oversized=json.loads(build.quality_report)['oversized_chunks']
        for cid in oversized:
            chunk=store.get_chunk(cid)
            units=[store.get_unit(build.build_id,uid) for uid in chunk.unit_refs]
            save('oversized-'+row['source_id'][:8]+'.json',{'chunk':asdict(chunk),'units':[asdict(u) for u in units]})
            print(json.dumps({'name':row['original_name'],'chars':len(chunk.search_text),'units':[
                {'id':u.unit_id,'chars':len(u.raw_text),'kind':u.kind,'page':u.location.page,'text_head':u.raw_text[:120]} for u in units]},ensure_ascii=False))
