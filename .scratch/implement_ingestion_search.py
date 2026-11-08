from pathlib import Path

def edit(name, old, new, count=None):
 p=Path(name); s=p.read_text(); n=s.count(old)
 assert n and (count is None or n==count),(name,old[:90],n,count)
 p.write_text(s.replace(old,new))

# Carry independent date options through every public search boundary.
files=['plugins/corpus/preparation/search_pg.py','plugins/corpus/preparation/read_pg.py','plugins/corpus/retrieval/hybrid.py','plugins/corpus/retrieval/native_pg.py','plugins/corpus/retrieval/native_live.py','plugins/tools/corpus_search.py']
for f in files:
 edit(f,'    published_to: str | None = None,\n','    published_to: str | None = None,\n    ingested_from: str | None = None,\n    ingested_to: str | None = None,\n    ingested_timezone: str = "Asia/Shanghai",\n')
for f in ['plugins/corpus/preparation/search_pg.py','plugins/corpus/preparation/read_pg.py','plugins/corpus/retrieval/hybrid.py']:
 # argument forwarding at differently indented call sites
 p=Path(f);s=p.read_text(); lines=s.splitlines(True); out=[]
 for line in lines:
  out.append(line)
  if line.strip()=='published_to=published_to,':
   prefix=line[:len(line)-len(line.lstrip())]
   out += [prefix+x+'\n' for x in ['ingested_from=ingested_from,','ingested_to=ingested_to,','ingested_timezone=ingested_timezone,']]
 p.write_text(''.join(out))
edit('plugins/corpus/retrieval/hybrid.py','        "published_to": published_to,','        "published_to": published_to,\n        "ingested_from": ingested_from,\n        "ingested_to": ingested_to,\n        "ingested_timezone": ingested_timezone,')
# Shared option validation in tool/service/native facade.
for f in ['plugins/corpus/service.py','plugins/tools/corpus_search.py','plugins/corpus/retrieval/native_live.py']:
 p=Path(f);s=p.read_text()
 if f.endswith('service.py'):
  s=s.replace('        published_to: str | None = None,\n','        published_to: str | None = None,\n        ingested_from: str | None = None,\n        ingested_to: str | None = None,\n        ingested_timezone: str = "Asia/Shanghai",\n')
 s=s.replace('from plugins.corpus.publication_dates import PublicationDateOptions, validate_range','from plugins.corpus.ingestion_dates import search_date_options')
 if not f.endswith('native_live.py'):
  s=s.replace('validate_range(published_from, published_to)','search_date_options(published_from, published_to, ingested_from, ingested_to, ingested_timezone)')
  indent='        ' if f.endswith('service.py') else '    '
  old=indent+'date_options: PublicationDateOptions = (\n'+indent+'    {"published_from": published_from, "published_to": published_to}\n'+indent+'    if published_from is not None or published_to is not None\n'+indent+'    else {}\n'+indent+')'
  assert old in s,f
  s=s.replace(old,indent+'date_options = search_date_options(\n'+indent+'    published_from, published_to, ingested_from, ingested_to, ingested_timezone\n'+indent+')')
 p.write_text(s)
edit('plugins/tools/corpus_search.py','return await asyncio.to_thread(_search_sync, query, limit, published_from, published_to)','return await asyncio.to_thread(\n        _search_sync, query, limit, published_from, published_to,\n        ingested_from, ingested_to, ingested_timezone,\n    )')
edit('plugins/tools/corpus_search.py','空查询必须提供发布日期范围','空查询必须提供发布日期或入库日期范围')
edit('plugins/corpus/service.py','query or publication date range is required','query or publication/ingestion date range is required')
# service.search forwarding (only this condition; no other scope contains the exact indent)
edit('plugins/corpus/service.py','        if published_from is not None or published_to is not None:\n','        if any(v is not None for v in (published_from, published_to, ingested_from, ingested_to)):\n')
edit('plugins/corpus/service.py','                published_to=published_to,\n','                published_to=published_to,\n                ingested_from=ingested_from,\n                ingested_to=ingested_to,\n                ingested_timezone=ingested_timezone,\n')
# Non-native filter SQL + timestamp enrichment in same read snapshot.
edit('plugins/corpus/preparation/search_pg.py','    from plugins.corpus.publication_dates import validate_range','    from plugins.corpus.publication_dates import validate_range\n    from plugins.corpus.ingestion_dates import sql_params')
edit('plugins/corpus/preparation/search_pg.py','    if not query.strip() and published_from is None and published_to is None:','    ingestion_params = sql_params(ingested_from, ingested_to, ingested_timezone)\n    if not query.strip() and published_from is None and published_to is None and not ingestion_params:')
edit('plugins/corpus/preparation/search_pg.py','除非提供发布日期范围','除非提供发布日期或入库日期范围')
edit('plugins/corpus/preparation/search_pg.py','        "date_from": date_from,','        **ingestion_params,\n        "date_from": date_from,')
edit('plugins/corpus/preparation/search_pg.py','    cur.execute(_SEARCH_SQL, params)','    from plugins.corpus.ingestion_dates import filter_sql\n\n    cur.execute(filter_sql(_SEARCH_SQL, params), params)')
edit('plugins/corpus/preparation/search_pg.py','    return _enrich_hits(cur, hits)','    hits = _enrich_hits(cur, hits)\n    return enrich_ingestion(cur, hits) if "ingested_start" in params else hits')
with Path('plugins/corpus/preparation/search_pg.py').open('a') as f:
 f.write('''\n\ndef enrich_ingestion(cur: psycopg.Cursor, hits: tuple[SearchHit, ...]) -> tuple[SearchHit, ...]:
    """Attach source timestamps from the same snapshot used by the filter."""
    from plugins.corpus.ingestion_dates import read_times

    if not hits:
        return hits
    times = read_times(cur, list({h.source_id for h in hits}))
    return tuple(replace(h, ingested_at=times.get(h.source_id)) for h in hits)
''')
edit('plugins/corpus/preparation/search_pg.py','    published: str | None = None','    published: str | None = None\n    ingested_at: str | None = None')
edit('plugins/corpus/retrieval/hybrid.py','                    cur.execute(_VECTOR_SQL, params)','                    from plugins.corpus.ingestion_dates import filter_sql\n\n                    cur.execute(filter_sql(_VECTOR_SQL, params), params)')
# enrich dense results after construction (inspect next step if needed)
# Tool and serializers must retain independent timestamp.
edit('plugins/corpus/service.py','    publication_date_basis: str = "unknown"','    publication_date_basis: str = "unknown"\n    ingested_at: str | None = None')
edit('plugins/corpus/service.py','                    publication_date_basis="admission" if hit.published else "unknown",','                    publication_date_basis="admission" if hit.published else "unknown",\n                    ingested_at=hit.ingested_at,')
edit('plugins/tools/corpus_search.py','                "published": hit.published,','                "published": hit.published,\n                "ingested_at": getattr(hit, "ingested_at", None),')
edit('plugins/corpus/search_refs.py','        "published": hit["published"],','        "published": hit["published"],\n        "ingested_at": hit.get("ingested_at"),')
edit('plugins/tools/corpus_search.py','_HIT_OPTIONAL_KEYS = ("title", "published", "snippet", "by_kind", "preview")','_HIT_OPTIONAL_KEYS = ("title", "published", "ingested_at", "snippet", "by_kind", "preview")')
# Only publication options go into publication coverage, with independent ingestion coverage.
edit('plugins/corpus/service.py','        if not query:\n            coverage["retrieval_mode"] = "publication_date"\n        if date_options:', '''        ingestion_filtered = ingested_from is not None or ingested_to is not None
        publication_filtered = published_from is not None or published_to is not None
        if not query:
            coverage["retrieval_mode"] = (
                "metadata_date" if ingestion_filtered and publication_filtered
                else "ingestion_date" if ingestion_filtered else "publication_date"
            )
        if ingestion_filtered:
            from plugins.corpus.ingestion_dates import coverage as ingestion_coverage

            coverage["ingestion_filter"] = {
                **ingestion_coverage(ingested_from, ingested_to, ingested_timezone),
                "scope": "active_sources", "unknown_time_source_count": None,
                "unknown_time_count_status": "not_measured",
            }
        if publication_filtered:''')
edit('plugins/corpus/service.py','                **date_options,\n                "bounds": "inclusive",','                "published_from": published_from,\n                "published_to": published_to,\n                "bounds": "inclusive",')
