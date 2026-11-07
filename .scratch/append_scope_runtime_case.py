import json
from pathlib import Path

path = Path('benchmarks/team_workflow/cases.json')
cases = json.loads(path.read_text())
assert len(cases) == 58
cases.append({
    'id': 'P45', 'layer': 'protocol', 'dimension': 'orchestration', 'split': 'development',
    'origin': 'F12 first general-scope model run: delivery/mandatory-review deadlock',
    'goal': '运行时必要核验未派发时协调仍开放，满足前置条件后才进入交付',
    'selectors': ['tests/test_team_requirement_scope.py::test_runtime_required_review_keeps_coordination_open'],
})
path.write_text(json.dumps(cases, ensure_ascii=False, indent=4)+'\n')
