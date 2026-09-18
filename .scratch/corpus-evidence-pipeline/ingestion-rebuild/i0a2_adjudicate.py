"""I0A-2 终态回填：U 裁决（2026-09-15"按方案执行+空文件删除"）写入登记，并生成 I0-C 清理清单。

产物（write-once）：
- i0a2-adjudicated-20260915.json：73 条逐条终态（decision_by=U）
- i0c-cleanup-list.json：删除对象精确清单（执行前置：M2 恢复验证 + I0-C 冻结 + I4 停写窗口 + U 执行签认；本阶段零执行）
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
IR = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"

BRIEF = IR / "i0a2-review-brief.json"
MANIFEST = IR / "dev-manifest.json"
DOCLIST = IR / "i0a2-doclist-findings.json"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    brief = json.loads(BRIEF.read_text(encoding="utf-8"))
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    doclist = json.loads(DOCLIST.read_text(encoding="utf-8"))
    db = {r["source_path"].replace("\\", "/"): r for r in doclist["documents"]}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    U = "U（2026-09-15 会话裁决：『按这个方案执行，无数据/空文件直接删除』）"

    by_id = {b["source_id"]: b for grp in brief["batch_decisions"] for b in grp["items"]}
    # A 批次：pipeline_note 4 + c3c4 误标 1
    a_ids = {b["source_id"] for b in brief["batch_decisions"][0]["items"]}
    b_ids = {b["source_id"] for b in brief["batch_decisions"][1]["items"]}
    c_ids = {b["source_id"] for b in brief["batch_decisions"][2]["items"]}
    d_ids = {b["source_id"] for b in brief["batch_decisions"][3]["items"]}
    broker = brief["per_item_broker_scope"]["items"]
    dev_paths = set(man["dev_selection_candidates"]["company"]) | set(man["dev_selection_candidates"]["industry"]) | set(man["dev_selection_candidates"]["macro"])
    gaosheng_sid = next(x["source_id"] for x in broker if "高盛" in x["path"] and "茅台" in x["path"])

    adjudicated = []
    for r in man["sources"]:
        sid = r["source_id"]
        t = sid[:12]
        rec = {"source_id": sid, "path": r["path"], "decision_by": U, "decided_at": now, "decision_note": ""}
        if t in a_ids:
            rec.update(decision="excluded", material_type="pipeline_artifact", batch="A", decision_note="流水线工作文件（c3c4 系机器误标 broker_research，已改判）")
        elif t in b_ids:
            rec.update(decision="excluded_from_active", material_type="personal_or_external_subscription", batch="B", decision_note="个人/外部订阅，保留原文与历史登记，不进活动索引")
        elif t in c_ids:
            rec.update(decision="excluded_from_active", material_type="internal_committee_report", batch="C", decision_note="内部投委会报告，主线外；DB 双路径重复转 I0-C")
        elif t in d_ids:
            rec.update(decision="excluded_from_active", material_type="internal_unattributed", batch="D", decision_note="无署名内部材料，U 批次授权；机器分类冲突已按主线外处理")
        else:
            item = next(x for x in broker if x["source_id"] == t)
            if t == gaosheng_sid:
                rec.update(decision="excluded", material_type="research_report", batch="broker",
                           decision_note="U 裁决：解析 0 块空文件，磁盘文件与 DB 记录均删除（执行于 I0-C/I4，M2 后）；文件删除后本登记保留为历史")
            else:
                rec.update(decision="admitted", material_type="research_report", batch="broker",
                           scope=item["suggested_scope"], scope_confidence=item["confidence"],
                           db_doc_id=item["db_doc_id"], decision_note="按建议；策略类低置信 scope 于 I0A-3 口径对齐复核" if item["confidence"] == "low" else "按建议")
                if item["is_holdout_frozen"]:
                    rec["holdout_protected"] = True
                    rec["decision_note"] = "历史扩大留出（manifest_hash 008474d3…），身份继承；不得作为开发材料"
                if item["is_dev_candidate"]:
                    rec["dev_selection"] = "approved"
        rec["db_doc_id"] = rec.get("db_doc_id") or (db.get(r["path"]) or {}).get("doc_id", "")
        adjudicated.append(rec)

    dev_items = []
    for scope, paths in man["dev_selection_candidates"].items():
        if isinstance(paths, list):
            for p in paths:
                dev_items.append({"scope": scope, "path": p, "dev_selection": "approved", "decision_by": U})
    out1 = {
        "artifact": "i0a2-adjudicated-20260915.json",
        "task": "I0A-2 来源终态登记（73 条）+ 开发材料批准",
        "decided_at": now,
        "decision_basis": U,
        "inputs": {"i0a2-review-brief.json": sha256(BRIEF), "dev-manifest.json": sha256(MANIFEST)},
        "counts": {
            "excluded_pipeline_A": len(a_ids),
            "excluded_from_active_B": len(b_ids),
            "excluded_from_active_C": len(c_ids),
            "excluded_from_active_D": len(d_ids),
            "excluded_empty_deleted": 1,
            "admitted_research_report": sum(1 for x in adjudicated if x["decision"] == "admitted"),
            "holdout_protected": sum(1 for x in adjudicated if x.get("holdout_protected")),
            "dev_approved": len(dev_items),
        },
        "dev_selection_approved": dev_items,
        "sources": adjudicated,
        "freeze_note": "分母冻结待：本登记 + I0A-3/4 达门后，冻结时点重测表计数（I0A-1 复核要求）",
    }
    (IR / "i0a2-adjudicated-20260915.json").write_text(json.dumps(out1, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── I0-C 清理清单（仅登记，本阶段零执行）──────────────────
    empties = [r for r in doclist["documents"] if r["status"] == "empty"]
    del_db = [
        {"doc_id": r["doc_id"], "source_path": r["source_path"], "reason": "empty 源文件已删（财联社系）"}
        for r in empties if r["source_path"].replace("\\", "/") not in {x["path"] for x in man["sources"]}
    ]
    gs = next(r for r in empties if r["source_path"].replace("\\", "/") in {x["path"] for x in man["sources"]})
    del_db.append({"doc_id": gs["doc_id"], "source_path": gs["source_path"], "reason": "empty 在盘（解析 0 块），U 裁决删除"})
    del_db += [
        {"doc_id": "undated_2a3e4387", "source_path": "data\\corpus\\天孚通信_投委会决策报告_20260830.md", "reason": "反斜杠路径重复入库（同文件正斜杠记录保留）"},
        {"doc_id": "undated_4aef3d9e", "source_path": "data\\corpus\\源杰科技_投委会决策报告_20260831.md", "reason": "同上"},
        {"doc_id": "undated_fe057e6c", "source_path": "data\\corpus\\生益科技_投委会决策报告_20260828.md", "reason": "同上"},
    ]
    out2 = {
        "artifact": "i0c-cleanup-list.json",
        "task": "I0-C 删除对象清单（U 裁决 2026-09-15 登记；本阶段零执行）",
        "generated_at": now,
        "db_delete": del_db,
        "disk_delete": [
            {"path": "data/corpus/高盛：GS 贵州茅台：市场化方案五— 2026 年 7 月飞天茅台出厂价与建议零售价意外开启第二轮上调；买入.pdf", "reason": "U 裁决：空文件（解析 0 块）删除；与 DB empty 记录删除绑定"},
            {"pattern": "data/corpus/*:Zone.Identifier", "count": 37, "reason": "Windows ADS 残留，U 裁决删除"},
        ],
        "keep_as_historical": [
            "4 条 ok 脱水/评级/调研 PDF（源删，R1 按建议保留历史）",
            "3 条正斜杠投委会记录（excluded_from_active 登记）",
        ],
        "execution_preconditions": [
            "M2 通过：I0B-2 隔离恢复验证成功（备份可用性证实）",
            "I0-C 设计复核与冻结完成（M3 门）",
            "I4 停写窗口 + U 最终执行签认（共库 apodex 同实例，删除为 DML）",
        ],
        "post_cleanup_math": "DB 89 − 21 = 68 条；磁盘 73 − 1 = 72 文件；活动集 admitted = 40 research report",
    }
    (IR / "i0c-cleanup-list.json").write_text(json.dumps(out2, ensure_ascii=False, indent=1), encoding="utf-8")

    print("adjudicated: %d sources; counts=%s" % (len(adjudicated), json.dumps(out1["counts"], ensure_ascii=False)))
    print("cleanup: db_delete=%d disk_delete=[1 file + 37 ADS]" % len(del_db))


if __name__ == "__main__":
    main()
