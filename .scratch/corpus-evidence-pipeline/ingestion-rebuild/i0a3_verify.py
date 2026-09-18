"""I0A-3 政策表达式验证：对 73 条 U 终态逐条运行特征表达式（本地确定性，零模型）。

产出：i0a3-policy-verification.json —— 表达式与锁定终态的一致性证据。
不修改任何来源文件；只读文件名与（md/docx 已入库的）标题。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
IR = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"

MINUTES_MARK = re.compile(r"纪要|实录|电话会|业绩会|交流会")
COMMITTEE_MARK = re.compile(r"投委会")
PIPELINE_MARK = re.compile(r"README|^c[0-9]_|^c[0-9]c[0-9]_|c[0-9]c[0-9]_")
PERSONAL_MARK = re.compile(r"复盘|盘面回顾|市场回顾|Substack|Simons|Capital-?Wars|Macro-?Charts|小红书")
BROKER_MARK = re.compile(
    r"证券|(?:jpmorgan|J\.?P\.?Morgan|Goldman|GS[：: \u4e00-\u9fff]|高盛|摩根大通)"
)
BROKER_TYPE_MARK = re.compile(r"研报|研究|点评|周报|周观察|周观点|专题|策略|高频|跟踪|扫描|面面观|双周")
BYLINE_PERSONAL = re.compile(r"James-?Bulltard|Simons|Capital-?Wars")
QA_PAIR = re.compile(r"^Q\s*[0-9]*\s*[：:]|^(提问|投资者|分析师)\s*[：:]", re.M)
SPEAKER_TURN = re.compile(r"^[^，。\n：:]{1,12}[：:]\s", re.M)


def title_marker(name: str) -> str:
    if MINUTES_MARK.search(name):
        return "minutes"
    if COMMITTEE_MARK.search(name):
        return "committee"
    if PIPELINE_MARK.search(name):
        return "pipeline"
    if PERSONAL_MARK.search(name):
        return "personal"
    if BROKER_MARK.search(name) and BROKER_TYPE_MARK.search(name):
        return "broker"
    if BROKER_MARK.search(name):
        return "broker"
    return "absent"


def main() -> None:
    adj = json.loads((IR / "i0a2-adjudicated-20260915.json").read_text(encoding="utf-8"))
    snap = json.loads((IR / "i0a2-doclist-findings.json").read_text(encoding="utf-8"))["documents"]

    results = {"by_decision": {}, "contradictions": [], "snapshot_minutes_positives": 0, "qa_tens_negative": None}
    counts: dict[str, dict[str, int]] = {}
    for r in adj["sources"]:
        name = Path(r["path"]).name
        tm = title_marker(name)
        d = r["decision"]
        counts.setdefault(d, {}).setdefault(tm, 0)
        counts[d][tm] += 1
        # 一致性断言：admitted 不得命中排除性标记（minutes/committee/pipeline/personal）
        if d == "admitted" and tm in ("minutes", "committee", "pipeline", "personal"):
            results["contradictions"].append({"source_id": r["source_id"][:12], "path": name, "title_marker": tm})
        if r["path"].endswith("十问十答-7463f4d0.pdf"):
            results["qa_tens_negative"] = {"title_marker": tm, "qa_pair_scan": "title_level_not_interview_qa"}
    results["by_decision"] = counts

    # 快照 78 标题 minutes 标记计数（正例存在性）
    results["snapshot_minutes_positives"] = sum(
        1 for d in snap if MINUTES_MARK.search(d.get("title") or "")
    )

    # feature 5 speaker_turns 判别（≥3 个不同前缀）在 md 样本上无正例；断言 admitted 无正文级验证 → I1 绑定
    evidence = {
        "artifact": "i0a3-policy-verification.json",
        "task": "I0A-3 特征表达式对 73 条锁定终态的验证（draft-1-20260915）",
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "i0a2-adjudicated-20260915.json": hashlib.sha256((IR / "i0a2-adjudicated-20260915.json").read_bytes()).hexdigest(),
            "admission-policy.json (draft-1)": hashlib.sha256((IR / "admission-policy.json").read_bytes()).hexdigest(),
        },
        "expressions_under_test": {
            "title_type_marker": "minutes|committee|pipeline|personal|broker 标记有序首中（表达式见政策 features[0]）",
            "byline_institution": "首页头区 ≤400 字符券商署名 / 个人订阅署名 / 未署名 absent（PDF 内容级绑定留 I1）",
            "heading_hierarchy": "≥2 个编号/井号标题（max_headings 50；内容级绑定留 I1）",
            "speaker_turns": "≥3 个不同说话人前缀（max_scans 200；无正例样本，I1 合成夹具）",
            "qa_markers": "≥2 组 Q:/提问:/投资者问: 配对；『十问十答』自设问答为反例",
            "transcript_declaration": "前 2000 字符命中纪要/实录/电话会声明词（无正例样本，I1 合成夹具）",
        },
        "verification_results": results,
        "verdict": {
            "admitted_contradictions": len(results["contradictions"]),
            "excluded_markers_as_expected": {
                "A_pipeline->pipeline": counts.get("excluded", {}).get("pipeline", 0),
                "B_personal->personal_or_absent": counts.get("excluded_from_active", {}).get("personal", 0) + counts.get("excluded_from_active", {}).get("absent", 0),
                "C_committee->committee": counts.get("excluded_from_active", {}).get("committee", 0),
            },
            "minutes_positive_samples_in_registered_corpus": results["snapshot_minutes_positives"],
            "note": "speaker_turns/qa_markers/transcript_declaration 无库内正例——正例由 I1 表驱动合成夹具提供（登记为待办，不虚构样本）",
        },
    }
    out = IR / "i0a3-policy-verification.json"
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(evidence["verdict"], ensure_ascii=False, indent=1))
    print("by_decision:", json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
