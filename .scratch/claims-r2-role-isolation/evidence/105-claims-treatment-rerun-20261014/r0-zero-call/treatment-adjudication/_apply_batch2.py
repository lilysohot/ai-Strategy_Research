import json

WS = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication/candidate-adjudications.worksheet.json"

BATCH2 = {
    20: ("matched", "NT-C07"),
    21: ("correct_extra", None),
    22: ("correct_extra", None),
    23: ("matched", "NT-C08"),
    24: ("duplicate", None),
    25: ("correct_extra", None),
    26: ("correct_extra", None),
    27: ("correct_extra", None),
    28: ("correct_extra", None),
    29: ("correct_extra", None),
    30: ("correct_extra", None),
    31: ("correct_extra", None),
    32: ("correct_extra", None),
    33: ("correct_extra", None),
    34: ("correct_extra", None),
    35: ("correct_extra", None),
    36: ("correct_extra", None),
    37: ("correct_extra", None),
    38: ("matched", "NT-C01"),
    39: ("correct_extra", None),
}

ws = json.load(open(WS))
adjs = ws["adjudications"]
assert len(adjs) >= 40

REVIEWER = "xyl"
for i, (judgement, gold) in BATCH2.items():
    a = adjs[i]
    a["judgement"] = judgement
    a["matched_gold_id"] = gold
    a["reviewer"] = REVIEWER
    a["adjudicator"] = REVIEWER
    a["review_status"] = "accepted"

json.dump(ws, open(WS, "w"), ensure_ascii=False, indent=2)
from collections import Counter
print("batch2 written. counts:", dict(Counter(a['judgement'] for a in adjs[20:40])))
