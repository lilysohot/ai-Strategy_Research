import json
from pathlib import Path
from tempfile import TemporaryDirectory

from plugins.tools._verification import VerificationCheck, reset_verification_scope, set_verification_scope, validate_results
from plugins.tools._web_handoff import render_web_handoff
from tests.test_agent_team_verification import make_bound, verdict_for
from tests.test_team_080_regressions import dispatch

root = Path('/home/administrator/.local/share/frontier-agent/web/runs/080ad8521962429a814171f48ffc7f60/run/agent/team-results/6b215a062236')
jobs = {n: json.loads((root/f'6b215a062236.job.{n}.json').read_text()) for n in [1,2,4,6,7]}
checks = jobs[6]['assignment_metadata']['verification_checks']
focus = checks[0]['subject']['text'] + '\n' + jobs[4]['final_content']
body = render_web_handoff({'6b215a062236.job.1': jobs[1]['metadata']['web_evidence']}, focus_text=focus, body_budget=12000, reference_budget=4000)
Path('.scratch/team-080-replayed-handoff.txt').write_text(body)
result = {'senate_table_visible': '| Democratic | 45 | 52 |' in body,
          'senate_outcome_visible': 'Democrats had won 20' in body,
          'handoff_chars': len(body)}
with TemporaryDirectory() as temp:
    path = Path(temp)
    bus, spec, _ = make_bound(path)
    bus._jobs['source'].result.metadata.update(jobs[2]['metadata'])
    subject = jobs[7]['assignment_metadata']['verification_checks'][0]['subject']['text']
    spec = VerificationCheck.model_validate({**spec.model_dump(), 'subject': {'text': subject}})
    bound, _ = dispatch(bus, spec, path)
    result['numeric_targets'] = bound[0].get('calculation_targets', [])
    token = set_verification_scope('replay', {'verification_checks': bound})
    try:
        validate_results([verdict_for(bound[0])])
        result['unsupported_pass_rejected'] = False
    except ValueError as exc:
        result['unsupported_pass_rejected'] = True
        result['rejection'] = str(exc)
    finally:
        reset_verification_scope(token)
Path('.scratch/team-080-replay.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
