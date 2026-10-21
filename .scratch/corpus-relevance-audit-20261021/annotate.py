"""Persist agent-reviewed relevance judgments, independent from retrieval code."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
authority = json.loads((HERE / "authority.json").read_text())
plan = json.loads((HERE / "plan.json").read_text())

# Judgments after inspecting the requested reports and pooled competing results.
# Facets mean relevant original evidence exists, not that the source claim is true.
positives = {
    "p01": {"16a9a510ef9e405f:body:0001": ("full", ["interconnect", "voltage"], "同时解释走线/互连电容与电压平方关系", ["互连电容", "降低工作电压"])},
    "p13": {"e1b21386e9b62dde:body:0002": ("full", ["manufacturing", "services"], "同一段比较美国8月制造业走弱和服务业走强", ["54.6%", "55.4%", "服务通胀粘性"])},
    "p16": {
        "7ceca88433b092ae:body:0001": ("full", ["huagong", "luxshare"], "摘要同时给出两家NPO展品", ["华工正源", "6.4T", "立讯技术", "3.2T"]),
        "7ceca88433b092ae:body:0003": ("full", ["huagong", "luxshare"], "展会前瞻总述同时给出两家NPO展品", ["华工正源", "6.4T", "立讯技术", "3.2T"]),
        "7ceca88433b092ae:body:0004": ("partial", ["huagong"], "华工正源6.4T去DSP NPO，未给立讯展品", ["华工正源", "6.4T", "去 DSP"]),
        "7ceca88433b092ae:body:0005": ("partial", ["luxshare"], "立讯3.2T NPO Live Demo；开头华工来源署名不是其展品证据", ["立讯技术", "3.2T NPO", "Live Demo"]),
    },
    "n01": {},
}
result = {"reviewer": "agent; not independently human-reviewed; sample seen during development",
          "rules": {"relevant": "full or partial contains substantive evidence for at least one requested facet",
                    "context": "topic-related/structural material without requested substantive evidence gets 0 for evidence precision",
                    "scope": "Positive questions explicitly name a report/institution; other-source material is excluded by provenance, not claimed factually false. This is an evaluation label, never a retrieval filter.",
                    "recall": "Within the completely inspected 3 requested report chunk inventories only; not universal corpus recall",
                    "negative": "n01 top10 pooled results reviewed for requested-company evidence; no positive denominator and no global absence claim"},
          "authority_sha256": hashlib.sha256((HERE / "authority.json").read_bytes()).hexdigest(), "cases": {}}
for case in plan["cases"]:
    cid = case["id"]
    pool = json.loads((HERE / "pools" / f"{cid}.json").read_text())
    labels = {}
    for key in sorted(set(pool["top10_pool"]) | set(pool["reviewed_report_scope"])):
        evidence = authority[key]
        if key in positives[cid]:
            grade, facets, reason, markers = positives[cid][key]
            normalized = "".join(evidence["text"].split())
            assert all("".join(m.split()) in normalized for m in markers)
            label = {"grade": grade, "facets": facets, "reason": reason, "support_markers": markers}
        elif cid == "n01":
            assert "紫荆量子" not in "".join(evidence["text"].split())
            label = {"grade": "entity_mismatch", "facets": [], "reason": "已核验候选为光力科技/其他公司或行业材料，没有问题公司的营收净利证据；不据此断言全库不存在", "support_markers": []}
        elif evidence["build_id"] != case["build_id"]:
            label = {"grade": "source_scope_mismatch", "facets": [], "reason": "不属于题目明确指定的报告，不能替代该报告的描述", "support_markers": []}
        else:
            label = {"grade": "context_only", "facets": [], "reason": "同报告内背景、其他对象/指标、图表碎片或声明；未提供本题所问的实质证据", "support_markers": []}
        label.update({"build_id": evidence["build_id"], "source_id": evidence["source_id"],
                      "text_sha256": hashlib.sha256(evidence["text"].encode()).hexdigest()})
        labels[key] = label
    result["cases"][cid] = {"question": case["question"], "build_id": case["build_id"],
                            "facets": sorted({f for v in positives[cid].values() for f in v[1]}),
                            "positive_chunks": sorted(positives[cid]), "labels": labels,
                            "report_chunks_reviewed": len(pool["reviewed_report_scope"]),
                            "pooled_chunks_reviewed": len(pool["top10_pool"])}
(HERE / "labels.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("Frozen judgments:", {k: len(v["labels"]) for k,v in result["cases"].items()})
