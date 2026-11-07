"""Read-only arithmetic gate replay against captured run 49e; no provider calls."""
import json
from pathlib import Path

from plugins.tools._calculation_verification import (
    CalculationCheck,
    calculation_targets,
    validate_calculations,
)

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/49e4f04b05ca46fda0ae4e4b71d1636a')
job = json.loads((root / 'run/agent/team-results/4934c2bd4dc3/4934c2bd4dc3.job.9.json').read_text())
binding = job['assignment_metadata']['verification_checks'][0]
result = job['metadata']['verification_events'][0]
calculations = [CalculationCheck.model_validate(c) for c in result['calculation_checks']]
findings = {
    'run_id': root.name,
    'check_id': binding['check_id'],
    'binding_targets': binding.get('calculation_targets', []),
    'extracted_targets': calculation_targets(binding['subject']['text']),
    'provided_calculations': len(calculations),
}
validate_calculations(binding, calculations)
findings['original_calculations_accepted'] = True
validate_calculations(binding, [calculations[0].model_copy(update={'expression': '0'})])
findings['negative_control_zero_expression_accepted_by_calculation_gate'] = True
try:
    validate_calculations({**binding, 'calculation_targets': ['-8.05%']}, calculations[:1])
except ValueError as exc:
    findings['forced_target_rejection'] = str(exc)
print(json.dumps(findings, ensure_ascii=False, indent=2))
