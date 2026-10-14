"""应用 2026-10-14 复核改判（A 档 3 条 + B 档 5 条）。

零调用。带改前值断言，改错即 fail。
A 档（原文反证，改 incorrect）：#12 共识次日股价 90 元 / #43 动PE隐含市值 475 亿 / #44 卖方参考市值 600 亿
B 档（判定不一致 + 重复渲染）：#60 成交额 103.15 亿 / #63 52周高 / #64 52周低 → correct_extra；
                              #42 OCF/扣非 0.32 / #90 26年底北美占比 85% → duplicate
"""

import json
from collections import Counter

WS = "/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/105-claims-treatment-rerun-20261014/r0-zero-call/treatment-adjudication/candidate-adjudications.worksheet.json"

# 1-based 序号 -> (改前 judgement, 改后 judgement, 依据)
FIXES = {
    12: ("correct_extra", "incorrect", "原文「不站 90 元共识当明天的地板价」= 共识目标价且是否定用法；候选改写为「共识预期次日股价」属语义改动"),
    43: ("correct_extra", "incorrect", "原文「动 PE 隐含的 475 亿…没给卖方 600」+ #29「定价约 475 亿 26E」⇒ 475 是净利润，候选写「市值」为对象错"),
    44: ("correct_extra", "incorrect", "同 #43：600 亿为净利润口径（对照 #30 卖方 560–667 亿），候选写「参考市值」为对象错"),
    60: ("incorrect", "correct_extra", "原文「成交额 103.15 亿元；」内容正确；同段 #59/#61/#62/#65 均判 correct_extra，判 incorrect 与同源条目不一致"),
    63: ("incorrect", "correct_extra", "原文「52 周（2025.09.01–2026.08.28）高 84.95 / 低 46.70」内容正确；同源 #65（45.3%）判 correct_extra，不一致"),
    64: ("incorrect", "correct_extra", "同上，52 周低 46.70 元内容正确"),
    42: ("correct_extra", "duplicate", "与 #18 同指 OCF/扣非 0.32（quote「OCF/扣非 0.32」vs「只盖住扣非的 0.32 倍」），同一事实两次渲染"),
    90: ("correct_extra", "duplicate", "与 #91 同指北美收入占比 85%（quote「预计北美市场收入占比将达到85%左右」vs「今年85%左右」），同一事实两次渲染"),
}

ws = json.load(open(WS))
adjs = ws["adjudications"]
assert len(adjs) == 93, len(adjs)

applied = []
for n, (before, after, why) in sorted(FIXES.items()):
    a = adjs[n - 1]
    assert a["judgement"] == before, f"#{n} 改前应为 {before}，实为 {a['judgement']}"
    a["judgement"] = after
    if after == "duplicate":
        a["matched_gold_id"] = None
    applied.append(
        {
            "seq": n,
            "candidate_id": a["candidate_id"],
            "claim_text": a["original_candidate"]["claim"]["claim_text"],
            "quote": a["original_candidate"].get("evidence_alignment", {}).get("source_quote"),
            "from": before,
            "to": after,
            "basis": why,
        }
    )

json.dump(ws, open(WS, "w"), ensure_ascii=False, indent=2)

cnt = Counter(a["judgement"] for a in adjs)
golds = sorted(a["matched_gold_id"] for a in adjs if a["judgement"] == "matched")
missing = [f"NT-C{i:02d}" for i in range(1, 21) if f"NT-C{i:02d}" not in golds]
num = cnt["matched"] + cnt["correct_extra"]
print("applied:", len(applied))
print("counts:", dict(cnt), "total:", sum(cnt.values()))
print("matched golds:", len(golds), "unique:", len(set(golds)), "missing:", missing)
print("precision: %.4f (%d/%d)" % (num / len(adjs), num, len(adjs)))
for run in ("claims-industrial-fulian", "claims-optical-module"):
    sub = [a for a in adjs if a["run"] == run]
    c = Counter(a["judgement"] for a in sub)
    n2 = c["matched"] + c["correct_extra"]
    print("  %s: %s prec=%.4f (%d/%d)" % (run, dict(c), n2 / len(sub), n2, len(sub)))

out = WS.replace("candidate-adjudications.worksheet.json", "adjudication-review-corrections.json")
json.dump(
    {
        "schema_version": "claims-treatment-adjudication-review-corrections-1",
        "status": "applied_pending_freeze",
        "reviewed_on": "2026-10-14",
        "model_calls": 0,
        "worksheet": "candidate-adjudications.worksheet.json",
        "corrections": applied,
        "post_counts": dict(cnt),
        "post_precision": {"numerator": num, "denominator": len(adjs), "value": num / len(adjs)},
    },
    open(out, "w"),
    ensure_ascii=False,
    indent=2,
)
print("wrote:", out)
