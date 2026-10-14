import json

GOLD = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json"
WS = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication/candidate-adjudications.worksheet.json"

gold = json.load(open(GOLD))
ws = json.load(open(WS))

out = []
out.append("========== GOLD NT-C* ==========")
for r in gold["records"]:
    if not r["record_id"].startswith("NT-C"):
        continue
    sf = r.get("semantic_fields", {})
    vn = r.get("value_normalization", {})
    pn = r.get("period_normalization", {})
    out.append(f"[{r['record_id']}] {r.get('quote')}")
    out.append(f"    subject={sf.get('subject')} metric={sf.get('metric')} period={sf.get('period')} "
               f"value={sf.get('value')} unit={sf.get('unit')} factuality={sf.get('factuality')}")
    out.append(f"    value_norm={vn.get('token')} scale={vn.get('scale')} | period_norm={pn.get('year_token')}-{pn.get('suffix')}")
    out.append("")

out.append("========== CANDIDATES (first 20) ==========")
adjs = ws["adjudications"]
for i, a in enumerate(adjs[:20]):
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

open("_extract_out.txt", "w").write("\n".join(out))
print("done, lines:", len(out))
