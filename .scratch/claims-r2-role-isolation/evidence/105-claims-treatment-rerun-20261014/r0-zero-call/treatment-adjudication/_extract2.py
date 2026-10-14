import json

WS = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication/candidate-adjudications.worksheet.json"
ws = json.load(open(WS))
adjs = ws["adjudications"]

out = []
for i in range(20, 40):
    a = adjs[i]
    c = a["original_candidate"]["claim"]
    out.append(f"[{i}] id={a['candidate_id'][:12]} run={a['run']} seq={c.get('seq')}")
    out.append(f"    claim_text={c.get('claim_text')}")
    out.append(f"    subject={c.get('subject')} metric={c.get('metric')} metric_raw={c.get('metric_raw')}")
    out.append(f"    period_raw={c.get('period_raw')} period_end={c.get('period_end')} period_grain={c.get('period_grain')}")
    out.append(f"    value_text={c.get('value_text')} value_num={c.get('value_num')} unit={c.get('unit')}")
    out.append(f"    kind={c.get('kind')} scope={c.get('scope')} quality_status={c.get('quality_status')} reason_codes={c.get('reason_codes')}")
    out.append(f"    evidence_quote={c.get('evidence_quote')}")
    out.append(f"    canonical.quote={a.get('canonical_observed_fields',{}).get('quote')}")
    out.append("")

open("_extract2_out.txt", "w").write("\n".join(out))
print("done lines:", len(out))
