from pathlib import Path

def edit(name, old, new):
 p=Path(name);s=p.read_text();assert old in s,(name,old[:100]);p.write_text(s.replace(old,new))
f='plugins/corpus/retrieval/native_live.py'
edit(f,'def refresh_on(cur: psycopg.Cursor, seed: NativeIndex) -> NativeIndex:', 'def refresh_on(cur: psycopg.Cursor, seed: NativeIndex, *, include_ingestion: bool = False) -> NativeIndex:')
edit(f,'    result.manifest["source_allowlist"] = [d["source_id"] for d in result.dates]', '''    if include_ingestion:
        from plugins.corpus.ingestion_dates import read_times

        times = read_times(cur, [d["source_id"] for d in result.dates])
        for record in result.dates:
            record["ingested_at"] = times.get(record["source_id"])
    result.manifest["source_allowlist"] = [d["source_id"] for d in result.dates]''')
edit(f,'def refresh(dsn: str, target: str, seed: NativeIndex) -> NativeIndex:', 'def refresh(\n    dsn: str, target: str, seed: NativeIndex, *, include_ingestion: bool = False\n) -> NativeIndex:')
edit(f,'            return refresh_on(cur, seed)','            return refresh_on(cur, seed, include_ingestion=include_ingestion)')
edit(f,'''    from plugins.corpus.publication_dates import (
        PublicationDateOptions,
        publication_matches,
        validate_range,
    )''','''    from plugins.corpus.ingestion_dates import ingestion_range, search_date_options
    from plugins.corpus.publication_dates import publication_matches''')
edit(f,'''    validate_range(published_from, published_to)
    date_filtered = published_from is not None or published_to is not None
    seed = configured_seed(target)
    index = refresh(dsn, target, seed)''','''    date_options = search_date_options(
        published_from, published_to, ingested_from, ingested_to, ingested_timezone
    )
    date_filtered = published_from is not None or published_to is not None
    ingestion_filtered = ingested_from is not None or ingested_to is not None
    seed = configured_seed(target)
    index = (
        refresh(dsn, target, seed, include_ingestion=True)
        if ingestion_filtered else refresh(dsn, target, seed)
    )''')
edit(f,'''    date_options: PublicationDateOptions = (
        {"published_from": published_from, "published_to": published_to} if date_filtered else {}
    )
''','')
edit(f,'                published=b.published or "",','''                published=b.published or "",
                ingested_at=next(
                    (d.get("ingested_at") for d in index.dates if d["source_id"] == b.source_id), None
                ),''')
edit(f,'else tuple(SourceDecision(bid, True, "publication_date_match", 0) for bid in groups)','else tuple(SourceDecision(bid, True, "date_metadata_match", 0) for bid in groups)')
edit(f,'"policy": REVISION if query.strip() else "publication_date_metadata",','"policy": REVISION if query.strip() else "date_metadata",')
edit(f,'''    return hits, coverage


def parse_locator''','''    if ingestion_filtered:
        from plugins.corpus.ingestion_dates import coverage as ingestion_coverage

        bounds = ingestion_range(ingested_from, ingested_to, ingested_timezone)
        matching = {d["source_id"] for d in index.dates if bounds.matches(d.get("ingested_at"))}
        combined = matching & {
            d["source_id"] for d in index.dates
            if not date_filtered or publication_matches(d, published_from, result.cutoff)
        }
        coverage["ingestion_filter"] = {
            **ingestion_coverage(ingested_from, ingested_to, ingested_timezone),
            "scope": "native_source_allowlist",
            "unknown_time_source_count": sum(not d.get("ingested_at") for d in index.dates),
            "matching_source_count": len(matching),
            "combined_matching_source_count": len(combined),
            "eligible_prose_source_count": len(combined & {c["source_id"] for c in index.chunks}),
            "selected_source_count": len(hits),
        }
    return hits, coverage


def parse_locator''')
f='plugins/corpus/retrieval/native_pg.py'
edit(f,'from plugins.corpus.publication_dates import publication_matches, validate_range','from plugins.corpus.publication_dates import publication_matches\nfrom plugins.corpus.ingestion_dates import ingestion_range, read_times, search_date_options')
# Reject ingestion metadata change between refresh and evidence delivery.
edit(f,'\n\ndef _load_blocks(','''
    ingestion_records = [d for d in index.dates if "ingested_at" in d]
    if ingestion_records:
        times = read_times(cur, [d["source_id"] for d in ingestion_records])
        if any(times.get(d["source_id"]) != d["ingested_at"] for d in ingestion_records):
            raise read_pg.IntegrityError("native_source_ingestion_changed_rebuild_required")


def _load_blocks(''')
edit(f,'''    trace: RetrievalTrace | None,
) -> NativeResult:''','''    trace: RetrievalTrace | None,
    retrieval_mode: str = "publication_date",
) -> NativeResult:''')
edit(f,'''    for block in sorted(
        blocks.values(), key=lambda b: (b.published or "", b.source_id, b.chunk_id)
    ):''','''    timestamps = {d["source_id"]: d.get("ingested_at") or "" for d in index.dates}
    for block in sorted(
        blocks.values(), key=lambda b: (
            timestamps[b.source_id] if retrieval_mode != "publication_date" else b.published or "",
            b.source_id, b.chunk_id,
        )
    ):''')
edit(f,'        trace.status = "native_publication_date"','        trace.status = "native_" + retrieval_mode')
edit(f,'        retrieval_mode="publication_date",','        retrieval_mode=retrieval_mode,')
edit(f,'''    validate_range(published_from, published_to)
    date_filtered = published_from is not None or published_to is not None''','''    options = search_date_options(
        published_from, published_to, ingested_from, ingested_to, ingested_timezone
    )
    date_filtered = published_from is not None or published_to is not None
    ingestion_filtered = ingested_from is not None or ingested_to is not None''')
edit(f,'(not query.strip() and not date_filtered)','(not query.strip() and not options)')
edit(f,'''    if not query.strip():
        return _search_publication_date(''','''    if ingestion_filtered:
        bounds = ingestion_range(ingested_from, ingested_to, ingested_timezone)
        sources = {d["source_id"] for d in index.dates if bounds.matches(d.get("ingested_at"))}
        scoped = copy(index)
        scoped.chunks = [c for c in index.chunks if c["source_id"] in sources]
        index = scoped
    if not query.strip():
        return _search_publication_date(''')
edit(f,'''            char_budget=char_budget,
            trace=trace,
        )
    config =''','''            char_budget=char_budget,
            trace=trace,
            retrieval_mode=(
                "metadata_date" if ingestion_filtered and date_filtered
                else "ingestion_date" if ingestion_filtered else "publication_date"
            ),
        )
    config =''')
# Native keyword path already filters chunks before preparing lexical/dense candidate tables.
# Attach dense timestamps on non-native hybrid path before fusion.
f='plugins/corpus/retrieval/hybrid.py'
s=Path(f).read_text();print(s[s.index('                    dense = _enrich_hits'):s.index('                    dense = _enrich_hits')+1700])
