from pathlib import Path
p=Path('plugins/corpus/service.py');s=p.read_text();old='''        search_date_options(
            published_from, published_to, ingested_from, ingested_to, ingested_timezone
        )
        date_options = search_date_options(''';assert old in s;s=s.replace(old,'        date_options = search_date_options(');s=s.replace('publication_date_filter_requires_new_read_chain','date_filter_requires_new_read_chain');p.write_text(s)
p=Path('plugins/tools/corpus_search.py');s=p.read_text();s=s.replace('''    try:
        search_date_options(
            published_from, published_to, ingested_from, ingested_to, ingested_timezone
        )
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc), "hits": []}, ensure_ascii=False)
    date_options = search_date_options(
        published_from, published_to, ingested_from, ingested_to, ingested_timezone
    )''','''    try:
        date_options = search_date_options(
            published_from, published_to, ingested_from, ingested_to, ingested_timezone
        )
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc), "hits": []}, ensure_ascii=False)''');p.write_text(s)
p=Path('docs/README.md');s=p.read_text();needle='| Understand how corpus retrieval enters Agent context and what is wired today | [Corpus retrieval and context wiring](corpus-retrieval.md) |';assert needle in s;s=s.replace(needle,needle+'\n| Search by first successful ingestion date independently of report publication dates | [入库时间检索](corpus-ingestion-search.md) |');p.write_text(s)
