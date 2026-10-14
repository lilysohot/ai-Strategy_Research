import json
from collections import Counter

WS = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication/candidate-adjudications.worksheet.json"

BATCH4 = {
    60: ("correct_extra", None),
    61: ("correct_extra", None),
    62: ("incorrect", None),
    63: ("incorrect", None),
    64: ("correct_extra", None),
    65: ("correct_extra", None),
    66: ("correct_extra", None),
    67: ("correct_extra", None),
    68: ("matched", "NT-C15"),
    69: ("matched", "NT-C16"),
    70: ("matched", "NT-C17"),
    71: ("matched", "NT-C18"),
    72: ("matched", "NT-C19"),
    73: ("correct_extra", None),
    74: ("correct_extra", None),
    75: ("correct_extra", None),
    76: ("correct_extra", None),
    77: ("matched", "NT-C11"),
    78: ("matched", "NT-C12"),
    79: ("matched", "NT-C13"),
}

# revise batch3 [58]: 涨跌幅 has no reference precedent; analogous microstructure metrics are correct_extra
REVISION = {58: ("correct_extra", None)}

ws = json.load(open(WS))
adjs = ws["adjudications"]
assert len(adjs) >= 80

REVIEWER = "xyl"
for i, (j, g) in {**BATCH4, **REVISION}.items():
    a = adjs[i]
    a["judgement"] = j
    a["matched_gold_id"] = g
    a["reviewer"] = REVIEWER
    a["adjudicator"] = REVIEWER
    a["review_status"] = "accepted"

json.dump(ws, open(WS, "w"), ensure_ascii=False, indent=2)
print("batch4 + [58] revision written.")
print("batch4 counts:", dict(Counter(a['judgement'] for a in adjs[60:80])))
print("[58] now:", adjs[58]['judgement'], adjs[58]['matched_gold_id'])
