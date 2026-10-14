import json
from collections import Counter

WS = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication/candidate-adjudications.worksheet.json"

BATCH3 = {
    40: ("correct_extra", None),
    41: ("correct_extra", None),
    42: ("correct_extra", None),
    43: ("correct_extra", None),
    44: ("correct_extra", None),
    45: ("correct_extra", None),
    46: ("correct_extra", None),
    47: ("correct_extra", None),
    48: ("correct_extra", None),
    49: ("correct_extra", None),
    50: ("correct_extra", None),
    51: ("correct_extra", None),
    52: ("correct_extra", None),
    53: ("correct_extra", None),
    54: ("correct_extra", None),
    55: ("correct_extra", None),
    56: ("matched", "NT-C08"),
    57: ("duplicate", None),
    58: ("incorrect", None),
    59: ("incorrect", None),
}

# cross-batch consistency fix: [23] collides with [56] on NT-C08; [56] more complete
CORRECTION = {23: ("duplicate", None)}

ws = json.load(open(WS))
adjs = ws["adjudications"]
assert len(adjs) >= 60

REVIEWER = "xyl"
for i, (j, g) in {**BATCH3, **CORRECTION}.items():
    a = adjs[i]
    a["judgement"] = j
    a["matched_gold_id"] = g
    a["reviewer"] = REVIEWER
    a["adjudicator"] = REVIEWER
    a["review_status"] = "accepted"

json.dump(ws, open(WS, "w"), ensure_ascii=False, indent=2)
print("batch3 + correction written.")
print("batch3 counts:", dict(Counter(a['judgement'] for a in adjs[40:60])))
print("[23] now:", adjs[23]['judgement'], adjs[23]['matched_gold_id'])
