"""Offline audit of captured execution; never execute commands from the trace."""
import ast
import collections
import datetime as dt
import json
import math
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / '.apodex/runs/20260925-182401+0800-react-75c6'
events = [json.loads(line) for line in (RUN / 'trace.jsonl').read_text().splitlines()]
tools = [e for e in events if e['t'] == 'tool']
checks = []


def check(name, passed, detail):
    checks.append(dict(name=name, passed=bool(passed), detail=detail))


def result(name):
    return json.loads(next(e['result'] for e in tools if e['name'] == name))


def date(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone(dt.timedelta(hours=8))).date().isoformat()


requested = collections.Counter((e['turn'], c['name']) for e in events if e['t'] == 'llm' for c in e.get('tool_calls', []))
returned = collections.Counter((e['turn'], e['name']) for e in tools)
check('tool_call_result_pairing', requested == returned, dict(total=len(tools), turns=events[-1]['turns']))
fetches = [json.loads(e['result']) for e in tools if e['name'] == 'corpus_fetch']
hit = result('corpus_search')['hits'][0]
check('fetch_identity_and_text', all(f['ok'] and f['active'] and f['text'] and f['doc_id'] == hit['doc_id'] and f['build_id'] == hit['build_id'] for f in fetches), {'fetched': len(fetches)})
missing = sorted(set(hit['context_locators']) - {f['locator'] for f in fetches})
check('all_returned_context_fetched', not missing, {'offered': len(hit['context_locators']), 'fetched': len(fetches), 'missing': missing})
coverage = result('data_coverage')
check('research_coverage_proven_complete', coverage['research_coverage']['availability'] != 'unknown' and not coverage['research_coverage']['reason_codes'], coverage['research_coverage'])

histories = [json.loads(e['result']) for e in tools if e['name'] == 'market_history']
history = histories[-1]
expected = [(r['date_ms'], r['close_price']) for r in history['items']]
check('history_count_order_unique', history['count'] == len(expected) == len(dict(expected)) and expected == sorted(expected), {'requested_calendar_days': history['days'], 'actual_rows': len(expected), 'first': date(expected[0][0]), 'last': date(expected[-1][0])})
for e in [e for e in tools if e['name'] == 'bash']:
    command = e['args']['command']
    code = command.split('\n', 1)[1].rsplit('\n', 1)[0]
    literals = {}
    for node in ast.parse(code).body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    literals[target.id] = value
    if 'hist' in literals:
        actual = literals['hist']
        check(f'calculation_input_turn_{e["turn"]}', actual == expected, {'rows': len(actual), 'mismatches': [i for i, pair in enumerate(zip(actual, expected)) if pair[0] != pair[1]]})

closes = [v for _, v in expected]
peak = closes[0]
drawdown = 0
for value in closes:
    peak = max(peak, value)
    drawdown = min(drawdown, value / peak - 1)
metrics = {'MA20': round(statistics.mean(closes[-20:]), 2), 'MA60': round(statistics.mean(closes[-60:]), 2), 'return21_pct': round((closes[-1] / closes[-22] - 1) * 100, 2), 'return63_pct': round((closes[-1] / closes[-64] - 1) * 100, 2), 'max_drawdown_pct': round(drawdown * 100, 2), 'volatility60_pct': round(statistics.stdev([closes[i] / closes[i-1] - 1 for i in range(len(closes)-60, len(closes))]) * math.sqrt(244) * 100, 1)}
check('reported_technical_metrics', metrics == {'MA20': 1281.34, 'MA60': 1286.32, 'return21_pct': -5.05, 'return63_pct': 3.52, 'max_drawdown_pct': -11.87, 'volatility60_pct': 23.5}, metrics)

calls = {c['id']: next(e['result'] for e in tools if e['turn'] == turn['turn'] and e['name'] == c['name'] and e['args'] == c['args']) for turn in events if turn['t'] == 'llm' for c in turn.get('tool_calls', [])}
for e in [e for e in tools if e['name'] == 'recover_result']:
    match = re.search(r'chars ([\d,]+)-([\d,]+) of ([\d,]+)\]\n', e['result'])
    if match:
        start, end, size = [int(s.replace(',', '')) for s in match.groups()]
        original = calls[e['args']['call_id']]
        check(f'recovered_slice_turn_{e["turn"]}', len(original) == size and original[start:end] == e['result'][match.end():match.end() + end - start], {'start': start, 'end': end, 'size': size})

raw = [json.loads(line) for line in (ROOT / '.apodex/market-trace/market_trace.jsonl').read_text().splitlines()]
for h in histories:
    matches = [(i+1, r) for i, r in enumerate(raw) if r['path'].endswith('/prices/historical') and r.get('params', {}).get('start') == str(h['start_ms']) and r.get('params', {}).get('end') == str(h['end_ms'])]
    check(f'raw_history_{h["days"]}', bool(matches) and all(all(row[k] == source[k] for k in row) for _, r in matches for row, source in zip(h['items'], r['raw']['data']['item'], strict=True)), {'raw_lines': [i for i, _ in matches]})
quote = result('market_quote')['items'][0]
matches = [(i+1, r) for i, r in enumerate(raw) if r['path'].endswith('/prices/snapshot') and r['as_of_ms'] == quote['as_of_ms']]
check('raw_quote_matches', bool(matches) and all(r['raw']['data']['item'][0]['last_price'] == quote['last_price'] for _, r in matches), {'raw_lines': [i for i, _ in matches], 'as_of': quote['as_of']})
valuation_matches = [(i+1, r) for i, r in enumerate(raw) if r['path'].endswith('/valuations/snapshot') and abs(r['as_of_ms'] - quote['as_of_ms']) <= 2000]
check('raw_valuation_matches', bool(valuation_matches) and all(all(r['raw']['data']['item'][0][key] == quote[key] for key in ['pe_ttm', 'pb_mrq', 'ps_ttm', 'pcf_ttm']) for _, r in valuation_matches), {'raw_lines': [i for i, _ in valuation_matches]})
financial = result('market_financials')
financial_matches = [(i+1, r) for i, r in enumerate(raw) if r['path'].endswith('/financials/income-statements') and abs(r['received_at_ms'] - quote['as_of_ms']) < 10000]
check('raw_financials_match', bool(financial_matches) and all(all(all(source[k] == v for k, v in row['values'].items()) and all(source[k] == row[k] for k in ['fiscal_year', 'fiscal_period', 'report_date_ms', 'period_end_ms', 'currency']) for row, source in zip(financial['items'], r['raw']['data']['item'], strict=True)) for _, r in financial_matches), {'raw_lines': [i for i, _ in financial_matches], 'years': [r['fiscal_year'] for r in financial['items']]})
report = RUN / 'outputs/report.md'
created = next(e for e in tools if e['name'] == 'create_file')
check('report_persisted_exactly', report.exists() and report.read_text() == created['args']['content'], str(report.relative_to(ROOT)))
check('report_window_label', '130 交易日' not in report.read_text() and '2026-05-18~' not in report.read_text(), {'actual_calendar_days': 130, 'actual_rows': len(expected), 'first_bar': date(expected[0][0])})
prior_year = [r for r in histories[0]['items'] if date(r['date_ms']).startswith('2025-')]
year_end = prior_year[-1]
check('report_year_end_anchor', year_end['close_price'] == 1402.0, {'last_observed_2025_bar': date(year_end['date_ms']), 'close': year_end['close_price'], 'return_to_last_pct': round((closes[-1] / year_end['close_price'] - 1) * 100, 2)})
check('cashflow_statement_fetched', any(e['name'] == 'market_financials' and e['args'].get('statement') == 'cashflow' for e in tools), {'actual_statements': [e['args'].get('statement') for e in tools if e['name'] == 'market_financials']})
check('strategy_closure_exercised', {'position_sizing', 'strategy_lint'} <= {e['name'] for e in tools} and (RUN / 'outputs/strategy.json').exists(), 'No sizing/lint calls or strategy card; original user supplied no sizing parameters.')
failures = [{'turn': e['turn'], 'name': e['name'], 'is_error': e['is_error']} for e in tools if '[Exit code 1]' in e['result'] or 'past the end' in e['result']]
output = {'checks': checks, 'semantic_failures_despite_is_error_false': failures, 'passed': sum(c['passed'] for c in checks), 'not_passed': sum(not c['passed'] for c in checks)}
Path(__file__).with_name('results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
for c in checks:
    print(('PASS' if c['passed'] else 'GAP') + ' ' + c['name'] + ': ' + json.dumps(c['detail'], ensure_ascii=False))
print('SEMANTIC_FAILURES', json.dumps(failures))
raise SystemExit(0 if all(c['passed'] for c in checks) else 1)
