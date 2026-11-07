import json
from pathlib import Path

for directory in ('team-scope-frozen-after', 'team-scope-runtime-translation', 'team-scope-runtime-prices'):
    folder = Path('results')/directory
    for trial in sorted(folder.glob('F*-r*')):
        if not (trial/'result.json').exists():
            print(directory, trial.name, 'RUNNING')
            continue
        status = json.loads((trial/'result.json').read_text())
        print('\nRESULT', directory, trial.name, status)
        if not (trial/'worker.json').exists():
            continue
        result = json.loads((trial/'worker.json').read_text()).get('result', {})
        metric = json.loads((trial/'metrics.json').read_text())
        print('METRIC', {k:metric.get(k) for k in ('attempts','known_prompt_tokens','first_research_report_s','tools','failure_reasons')})
        print('ANSWER', result.get('final_answer', '')[:7000])
        contract = result.get('report_contract') or {}
        print('BOARD', contract.get('task_board'))
        print('GAPS', contract.get('gaps'))
