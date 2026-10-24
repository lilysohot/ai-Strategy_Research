"""Authenticated HTTP plus actual tool wire contract against released configuration."""
import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx
import psycopg
from dotenv import load_dotenv

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
from server.config import get_config
from server.security import create_access_token
from plugins.corpus.search_evidence import search_evidence_items
from plugins.tools.corpus_search import corpus_search
from plugins.tools.corpus_fetch import corpus_fetch
from plugins.corpus.retrieval.native_live import configured_seed, refresh
from plugins.corpus.service import dsn

QUERIES = [
    '2026年8月茅台调价后，线上和自营店的价格分别怎么跟批价、成交价联动？为什么这样能稳价？',
    '可插拔光模块现在卡在哪些系统瓶颈上？改用NPO或CPO，对可靠性有什么更高要求？',
]


async def main():
    cfg = get_config()
    expected_index = refresh(dsn(), 'postgres', configured_seed('postgres')).index_id
    with psycopg.connect(cfg.database_url.replace('postgresql+asyncpg://', 'postgresql://', 1)) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        uid = conn.execute("SELECT id FROM users WHERE status='active' ORDER BY created_at LIMIT 1").fetchone()[0]
    token = create_access_token(uid, ttl_s=180)
    results = []
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=25,
                      headers={'Authorization': 'Bearer ' + token}) as client:
        for number, query in enumerate(QUERIES, 1):
            start = time.monotonic()
            response = client.get('/api/corpus/search', params={'query': query, 'limit': 1})
            response.raise_for_status()
            payload = response.json()
            search_ms = round((time.monotonic() - start) * 1000)
            coverage = payload['coverage']
            assert coverage['retrieval_mode'] == 'hybrid', coverage
            assert coverage['native']['sources'] == 23
            assert coverage['native']['chunks'] == coverage['native']['ready_vectors'] == 585
            assert coverage['native']['index_id'] == expected_index
            assert payload['hits']
            hit = payload['hits'][0]
            assert hit['evidence_spans']
            fetched = {}
            start = time.monotonic()
            for span in hit['evidence_spans']:
                locator = hit['context_locators'][span['member'] - 1]
                if locator not in fetched:
                    response = client.get('/api/corpus/documents/' + hit['doc_id'], params={'locator': locator})
                    response.raise_for_status()
                    fetched[locator] = response.json()['text']
                raw = fetched[locator]
                quote = hit['snippet'][span['snippet_start']:span['snippet_end']]
                assert raw[span['start']:span['end']] == quote
                assert hashlib.sha256(raw.encode()).hexdigest() == span['text_sha256']
                assert hashlib.sha256(quote.encode()).hexdigest() == span['quote_sha256']
            fetch_ms = round((time.monotonic() - start) * 1000)
            start = time.monotonic()
            wire = json.loads(await corpus_search.ainvoke({'query': query, 'limit': 1}))
            tool_search_ms = round((time.monotonic() - start) * 1000)
            (HERE / f'probe-{number}.json').write_text(json.dumps({'http': payload, 'tool': wire}, ensure_ascii=False, indent=2) + '\n')
            assert wire['ok'] and wire['hits']
            tool_hit = wire['hits'][0]
            assert wire['coverage']['native']['index_id'] == expected_index
            items = search_evidence_items(tool_hit)
            assert len(items) == len(tool_hit['evidence_spans']) > 0
            for evidence in items:
                response = client.get('/api/corpus/documents/' + tool_hit['doc_id'], params={'locator': evidence['locator']})
                response.raise_for_status()
                raw = response.json()['text']
                assert raw[evidence['fragment']['start']:evidence['fragment']['end']] == evidence['text']
                assert hashlib.sha256(raw.encode()).hexdigest() == evidence['text_sha256']
            start = time.monotonic()
            item = items[0]
            tool_fetch = json.loads(await corpus_fetch.ainvoke({'doc_id': tool_hit['doc_id'],
                'locator': item['locator'], 'view': 'compact', 'max_chars': 12000}))
            tool_fetch_ms = round((time.monotonic() - start) * 1000)
            assert tool_fetch['ok']
            assert hashlib.sha256(tool_fetch['text'].encode()).hexdigest() == item['text_sha256']
            (HERE / f'query-{number}.json').write_text(json.dumps({'http': payload,
                'tool': wire, 'fetch_texts': fetched}, ensure_ascii=False, indent=2) + '\n')
            results.append({'query': query, 'mode': coverage['retrieval_mode'],
                'native': coverage['native'], 'evidence_contract': tool_hit['evidence_contract'],
                'verified_spans': len(items), 'fetched_members': len(fetched),
                'http_search_ms': search_ms, 'http_fetch_ms': fetch_ms,
                'tool_search_ms': tool_search_ms, 'tool_fetch_ms': tool_fetch_ms,
                'tool_mode': wire['coverage']['retrieval_mode'],
                'tool_fallback': wire['coverage'].get('fallback_reason'),
                'http_tool_handles_identical': tool_hit['context_locators'] == hit['context_locators'],
                'all_quotes_match_raw_and_hashes': True})
        previous = json.loads((ROOT / '.scratch/corpus-production-release-20261022/http-smoke.json').read_text())
        for old in previous['fetches']:
            response = client.get('/api/corpus/documents/' + old['doc_id'], params={'locator': old['locator']})
            response.raise_for_status()
            assert response.json()['text'] and response.json()['locator'] == old['locator']
        report = {'cases': results, 'historical_handles_readable': len(previous['fetches']),
            'health': {p: client.get('/' + p).status_code for p in ('healthz', 'readyz')}}
        assert all(v == 200 for v in report['health'].values())
        (HERE / 'smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False))


asyncio.run(main())
