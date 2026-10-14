import json, copy

WS = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication/candidate-adjudications.worksheet.json"

# index -> (judgement, matched_gold_id)
BATCH1 = {
    0:  ("matched", "NT-C09"),
    1:  ("correct_extra", None),
    2:  ("correct_extra", None),
    3:  ("correct_extra", None),
    4:  ("matched", "NT-C10"),
    5:  ("correct_extra", None),
    6:  ("correct_extra", None),
    7:  ("correct_extra", None),
    8:  ("matched", "NT-C04"),
    9:  ("correct_extra", None),
    10: ("correct_extra", None),
    11: ("correct_extra", None),
    12: ("matched", "NT-C02"),
    13: ("correct_extra", None),
    14: ("matched", "NT-C03"),
    15: ("correct_extra", None),
    16: ("duplicate", None),
    17: ("correct_extra", None),
    18: ("matched", "NT-C05"),
    19: ("matched", "NT-C06"),
}

ws = json.load(open(WS))
adjs = ws["adjudications"]
assert len(adjs) >= 20, len(adjs)

REVIEWER = "xyl"
for i, (judgement, gold) in BATCH1.items():
    a = adjs[i]
    a["judgement"] = judgement
    a["matched_gold_id"] = gold
    a["reviewer"] = REVIEWER
    a["adjudicator"] = REVIEWER
    a["review_status"] = "accepted"

json.dump(ws, open(WS, "w"), ensure_ascii=False, indent=2)
print("batch1 written. counts:", {k: sum(1 for a in adjs[:20] if a['judgement']==k) for k in ('matched','correct_extra','incorrect','duplicate')})
