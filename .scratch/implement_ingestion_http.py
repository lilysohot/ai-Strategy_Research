from pathlib import Path

def edit(f,a,b):
 p=Path(f);s=p.read_text();assert a in s,(f,a[:80]);p.write_text(s.replace(a,b))
edit('plugins/corpus/retrieval/hybrid.py','                hits = fuse(lexical, dense) if complete else lexical','''                if "ingested_start" in params and dense:
                    from plugins.corpus.preparation.search_pg import enrich_ingestion

                    dense = enrich_ingestion(cur, dense)
                hits = fuse(lexical, dense) if complete else lexical''')
edit('plugins/tools/corpus_search.py','    日期范围是发布日期闭区间，不是上传时间或正文提及的日期。相对日期应根据本轮','''    published_from/published_to 是研报发布日期范围；ingested_from/ingested_to 是资料
    首次成功入库（首次进入可检索范围）的日期范围，重建/重新解析不刷新该时间。
    两组条件独立；同时传入时取交集。发布日期未知的资料仍可按入库时间检索。
    入库时间未知的历史资料只在显式入库筛选时排除，coverage.ingestion_filter 披露限制。
    “今天收录/昨天入库”用 ingested_*，“昨天发布的研报”用 published_*；不可互相替代。
    入库日期按 ingested_timezone 的本地自然日包含首尾两天，返回 ingested_at 为带时区时间戳。
    只查日期时 query 可留空。相对日期应根据本轮''')
edit('plugins/tools/corpus_search.py','        published_to: 可选发布日期上界，YYYY-MM-DD，包含当天；单日查找两界相同。','''        published_to: 可选发布日期上界，YYYY-MM-DD，包含当天；单日查找两界相同。
        ingested_from: 可选首次成功入库日期下界，YYYY-MM-DD，包含当天。
        ingested_to: 可选首次成功入库日期上界，YYYY-MM-DD，包含当天。
        ingested_timezone: 入库日期所用 IANA 时区，默认 Asia/Shanghai；其他时区需显式传入。''')
f='server/routes/corpus.py'
edit(f,'    query: str = Query(min_length=1, max_length=400),','''    query: str = Query(default="", max_length=400),
    published_from: str | None = None,
    published_to: str | None = None,
    ingested_from: str | None = None,
    ingested_to: str | None = None,
    ingested_timezone: str = "Asia/Shanghai",''')
edit(f,'''    service = _corpus_service()
    try:
        hits, coverage = service.search_with_coverage(query, limit=limit)''','''    from plugins.corpus.ingestion_dates import search_date_options

    try:
        options = search_date_options(
            published_from, published_to, ingested_from, ingested_to, ingested_timezone
        )
        if not query.strip() and not options:
            raise ValueError("query or publication/ingestion date range is required")
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    service = _corpus_service()
    try:
        hits, coverage = service.search_with_coverage(query, limit=limit, **options)''')
