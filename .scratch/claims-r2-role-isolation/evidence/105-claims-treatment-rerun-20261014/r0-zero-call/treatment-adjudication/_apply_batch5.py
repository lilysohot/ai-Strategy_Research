import json
from collections import Counter

WS = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication/candidate-adjudications.worksheet.json"

BATCH5 = {
    80: ("correct_extra", None),
    81: ("correct_extra", None),
    82: ("correct_extra", None),
    83: ("correct_extra", None),
    84: ("correct_extra", None),
    85: ("correct_extra", None),
    86: ("matched", "NT-C14"),
    87: ("matched", "NT-C20"),
    88: ("correct_extra", None),
    89: ("correct_extra", None),
    90: ("correct_extra", None),
    91: ("correct_extra", None),
    92: ("correct_extra", None),
}

ws = json.load(open(WS))
adjs = ws["adjudications"]
assert len(adjs) == 93

REVIEWER = "xyl"
for i, (j, g) in BATCH5.items():
    a = adjs[i]
    a["judgement"] = j
    a["matched_gold_id"] = g
    a["reviewer"] = REVIEWER
    a["adjudicator"] = REVIEWER
    a["review_status"] = "accepted"

json.dump(ws, open(WS, "w"), ensure_ascii=False, indent=2)

# global stats
cnt = Counter(a["judgement"] for a in adjs)
matched_golds = sorted(set(a["matched_gold_id"] for a in adjs if a["judgement"] == "matched"))
print("ALL 93 written. global counts:", dict(cnt))
print("distinct matched golds:", len(matched_golds), matched_golds)
print("unmatched golds:", [f"NT-C{n:02d}" for n in range(1,21) if f"NT-C{n:02d}" not in matched_golds])
