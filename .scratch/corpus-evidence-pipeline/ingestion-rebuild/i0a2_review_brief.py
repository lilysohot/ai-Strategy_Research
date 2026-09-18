"""生成 I0A-2 待签批复核清单（建议，不构成批准——架构 §5.2）。

输入绑定：dev-manifest.json / i0a2-doclist-findings.json / 快照 documents.csv /
旧审核 CSV ×2 / expanded-holdout 报告与冻结。输出：i0a2-review-brief.json。
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
IR = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"

MANIFEST = IR / "dev-manifest.json"
DOCLIST = IR / "i0a2-doclist-findings.json"
SNAPCSV = REPO / "data/corpus_full_backup_v2/documents.csv"
REVIEW84 = REPO / "data/corpus/.audit/c1_full84_doc_kind_review_20260912.csv"
REVIEW87 = REPO / "data/corpus/.audit/c1_full87_doc_kind_review_20260912.csv"

COMPANY_KW = ("600519", "300480", "业绩点评", "贵州茅台", "茅台", "台达电子", "新股精要", "光力科技")
MACRO_KW = (
    "宏观", "策略周报", "策略周评", "策略定期", "海外周报", "海外跟踪", "非农", "高频数据",
    "数据面面观", "议息", "独立行情", "流动性", "a股策略", "周观点",
)
STRATEGY_KW = ("策略周报", "策略周评", "策略定期", "a股策略", "独立行情", "周观点", "数据面面观")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    doclist = json.loads(DOCLIST.read_text(encoding="utf-8"))
    snap = {r["source_path"]: r for r in csv.DictReader(SNAPCSV.open(encoding="utf-8-sig"))}
    db = {r["source_path"]: r for r in doclist["documents"]}
    db_norm = {k.replace("\\", "/"): v for k, v in db.items()}

    sources = man["sources"]
    brief: dict = {
        "artifact": "i0a2-review-brief.json",
        "task": "I0A-2 来源与开发分母：待 U 签批复核清单（建议，不构成批准）",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "磁盘 rglob 清单 × PG documents 只读清单 × 2026-09-11 快照 CSV 三方对账；机器建议仅梳理，终态待 U",
        "inputs": {
            "dev-manifest.json": sha256(MANIFEST),
            "i0a2-doclist-findings.json": sha256(DOCLIST),
            "documents_csv_snapshot": sha256(SNAPCSV),
            "c1_full84_doc_kind_review": sha256(REVIEW84),
            "c1_full87_doc_kind_review": sha256(REVIEW87),
            "expanded_holdout_manifest_hash": "008474d37099b5d2716ca2b73366f4b3a9e14f5eb9be73ebc3cea66676b0bfd3",
        },
    }

    # ── 1. 89/73/78 差异闭合解释 ──────────────────────────────
    after = sorted(set(db) - set(snap))
    ghost = sorted(set(db) - set(fls := {r["path"] for r in sources}))
    never = sorted(fls - set(db_norm))
    dup_backslash = [p for p in ghost if "\\" in p]
    empty_on_disk = [r for r in doclist["documents"] if r["status"] == "empty" and r["source_path"].replace("\\", "/") in fls]
    empty_deleted = [r["source_path"] for r in doclist["documents"] if r["status"] == "empty" and r["source_path"].replace("\\", "/") not in fls]
    ok_deleted = [r["source_path"] for r in doclist["documents"] if r["status"] == "ok" and r["source_path"].replace("\\", "/") not in fls]
    brief["reconciliation"] = {
        "counts": {"db_documents": 89, "snapshot_2026_09_11": 78, "disk_source_like_files": 73},
        "closed_math": [
            "78→89：快照（09-11 导出）后新入库 11 条（4 PDF + 2 内部 md/docx + 卫星化学/工业富联 + 3 投委会反斜杠路径重复）；快照后从库消失 0 条",
            "89→73：DB 89 条记录 = 68 条对应磁盘现存文件 + 21 条源文件已删（4 ok 脱水/评级/调研 PDF + 17 empty 财联社系）；磁盘 73 = 68 已入库 + 5 从未入库（4 流水线 md + README）",
            "3 份投委会 md 各入库 2 次（反斜杠+正斜杠路径，content_hash 不同）：DB 记录层 +3 重复",
            "empty=18：17 源文件已删 + 1 高盛茅台 PDF 在盘（解析产出 0 块，可重解析）",
            "ingested_at 集合 09-08~09-14，与快照时点差自洽",
        ],
        "db_only_after_snapshot": [p.split("/")[-1] for p in after],
        "ghost_paths_deleted_source": {
            "ok_status": [p.split("/")[-1] for p in ok_deleted],
            "empty_status": [p.split("/")[-1] for p in empty_deleted],
            "backslash_duplicates": [p.split("\\")[-1] for p in dup_backslash],
        },
        "never_ingested": [p.split("/")[-1] for p in never],
        "empty_on_disk_reparse_candidate": [r["source_path"].split("/")[-1] for r in empty_on_disk],
        "zone_identifier_remnants": "37 个 Windows ADS 残留（*​:Zone.Identifier），rglob 观察到但未计入 73；建议列入 I0-C 清理清单",
    }

    # ── 2. 批量排除建议 ──────────────────────────────────────
    def pick(pred):
        return [r for r in sources if pred(r)]

    pipeline = pick(lambda r: (r["machine_suggestion"] or {}).get("material_type") == "pipeline_note")
    c3c4 = pick(lambda r: "c3c4_field_gold_instructions" in r["path"])
    personal = pick(lambda r: (r["machine_suggestion"] or {}).get("material_type") == "personal_or_external_subscription")
    committee = pick(lambda r: (r["machine_suggestion"] or {}).get("material_type") == "internal_committee_report")
    unsigned = pick(lambda r: (r["machine_suggestion"] or {}).get("material_type") == "internal_or_unsigned_analysis")
    limayue = pick(lambda r: r["path"].endswith("5月：锂电铜箔和电子铜箔.md"))

    brief["batch_decisions"] = [
        {
            "batch_id": "A",
            "title": "流水线工作文件排除（5 份，非研报工作文件）",
            "recommendation": "excluded / material_type=pipeline_artifact",
            "basis": "任务清单 I0A-2 与架构 §1：流水线产物不是语料来源；其中 c3c4_field_gold_instructions 机器误标 broker_research，实为金标标注指引",
            "items": [
                {"path": r["path"], "source_id": r["source_id"][:12], "note": (r["machine_suggestion"] or {}).get("note", "")}
                for r in (pipeline + c3c4)
            ],
        },
        {
            "batch_id": "B",
            "title": "个人/外部订阅材料（19 份）",
            "recommendation": "excluded_from_active / material_type=personal_or_external_subscription，保留原文与历史登记（架构 §1：个人记录等主线外材料保留原文与历史）",
            "items": [{"path": r["path"], "source_id": r["source_id"][:12]} for r in personal],
        },
        {
            "batch_id": "C",
            "title": "内部投委会决策报告（6 份，3 公司各双份入库）",
            "recommendation": "excluded_from_active / material_type=internal_committee_report（主线外）；其 DB 重复记录（反斜杠+正斜杠各 1）列入 I0-C 清理建议，本清单不授权任何删除",
            "items": [{"path": r["path"], "source_id": r["source_id"][:12]} for r in committee],
        },
        {
            "batch_id": "D",
            "title": "无署名/归属不明内部材料（2 份，待复核）",
            "recommendation": "pending_review——机器分类冲突或无机构署名，需 U 判定材料类型；不猜测消解",
            "items": [
                {"path": unsigned[0]["path"], "source_id": unsigned[0]["source_id"][:12],
                 "machine": "internal_or_unsigned_analysis", "note": "docx 无署名内部技术分析"},
                {"path": limayue[0]["path"], "source_id": limayue[0]["source_id"][:12],
                 "machine": "broker_research（疑似误标）", "note": "md 无机构/作者署名，DB 已入库 status=ok"},
            ],
        },
    ]

    # ── 3. 43→41 券商研报逐条 scope 建议 ─────────────────────
    broker = pick(lambda r: (r["machine_suggestion"] or {}).get("material_type") == "broker_research")
    broker = [r for r in broker if r not in c3c4 and r not in limayue]
    holdout_suffixes = ("2594e01d", "d571f138", "65b4b040")
    dev_paths = {p for v in man["dev_selection_candidates"].values() if isinstance(v, list) for p in v}
    per_item = []
    for r in sorted(broker, key=lambda x: x["path"]):
        name = r["path"].split("/")[-1]
        scope = next(("company" for k in COMPANY_KW if k in name), None) or next(("macro" for k in MACRO_KW if k in name), "industry")
        conf = "low" if scope == "macro" and any(k in name for k in STRATEGY_KW) else "medium"
        per_item.append({
            "path": r["path"],
            "source_id": r["source_id"][:12],
            "suggested_scope": scope,
            "confidence": conf,
            "note": "策略类归属（宏观 vs 行业）待 I0A-3 口径对齐" if conf == "low" else "",
            "db_doc_id": (db_norm.get(r["path"]) or {}).get("doc_id", ""),
            "is_holdout_frozen": any(h in name for h in holdout_suffixes),
            "is_dev_candidate": r["path"] in dev_paths,
        })
    brief["per_item_broker_scope"] = {
        "title": "券商研报 41 份逐条 scope 终态（company/industry/macro）",
        "recommendation": "admitted / material_type=research_report，scope 按 suggested_scope 或 U 改判；低置信 %d 条待 I0A-3 表达式对齐" % sum(1 for x in per_item if x["confidence"] == "low"),
        "items": per_item,
        "low_confidence_count": sum(1 for x in per_item if x["confidence"] == "low"),
    }

    # ── 4. 旧审核继承与留出 ─────────────────────────────────
    brief["inheritance_and_holdout"] = {
        "doc_kind_review_20260912": "c1_full84/87 两份 CSV 共 80 条 doc_kind 校正建议（industry→company 14、→macro 3），review_decision 全部为空——旧人工审核未出终态，仅作建议继承，不构成 I0A-2 裁决",
        "gold_candidates": "c1_full87_gold_candidates_merged_smoke30（块级 claims 金标候选）与 r1/r2 material gold 契约冻结文件归属 I0A-4 金标线，不在本清单裁决",
        "holdout_frozen": {
            "rule": "历史留出身份必须继承：以下 3 份曾冻结为扩大留出（manifest_hash 008474d3…），不得登记为开发材料",
            "items": [
                {"file": "…贝特利-2594e01d.pdf", "page": 4, "source_rev": "f0e67b732b3f6d7b", "target": "客户销售额与收入占比 12 单元格"},
                {"file": "…华泰宏观海外周报-d571f138.pdf", "page": 1, "source_rev": "5e30537691c88e4e", "target": "非农 actual 16.2 / consensus 5.6"},
                {"file": "…中银高频数据扫描-65b4b040.pdf", "page": 1, "source_rev": "bd0a65b7c6fe481d", "target": "非农就业人数同比增长 0.38%"},
            ],
            "dev_candidate_conflict": "无——3 份留出均不在 manifest 开发材料候选中",
        },
    }

    # ── 5. 需 U 单独裁决的库记录事项 ─────────────────────────
    brief["db_record_decisions"] = [
        {"id": "R1", "title": "17 条 empty 财联社系（源文件已删）",
         "recommendation": "保留 DB 记录为历史（不进入新分母）；源文件无法重新登记——登记分母以磁盘现存文件为准；如需找回源文件由 U 提供路径"},
        {"id": "R2", "title": "4 条 ok 脱水/评级/调研 PDF（源文件已删，聚合类）",
         "recommendation": "同 R1：保留历史；聚合类材料类型归属待 U 定（research_report_aggregate 或 excluded）"},
        {"id": "R3", "title": "1 条 empty 在盘（高盛茅台 PDF，解析 0 块）",
         "recommendation": "登记后重解析验证（I1 链路验证样本候选，非 I0 写操作）"},
        {"id": "R4", "title": "3 对投委会重复 DB 记录（content_hash 不同）",
         "recommendation": "I0-C 清理清单建议项；本阶段不授权删除"},
        {"id": "R5", "title": "37 个 Zone.Identifier ADS 残留",
         "recommendation": "I0-C 清理清单建议项；不影响 73 计数"},
    ]

    # ── 6. 分母汇总（按建议终态预览，非决定） ────────────────
    brief["denominator_preview"] = {
        "note": "按上述建议全部通过时的分母预览；任一批次被 U 改判则重算",
        "disk_files": 73,
        "excluded_pipeline": len(pipeline) + len(c3c4),
        "excluded_from_active": len(personal) + len(committee),
        "pending_review": len(unsigned) + len(limayue),
        "broker_scope_items": len(per_item),
        "holdout_protected": 3,
        "dev_candidates_confirmed": sorted(p.split("/")[-1][:60] for p in dev_paths),
    }

    out = IR / "i0a2-review-brief.json"
    out.write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written {out}")
    print("batches: A=%d B=%d C=%d D=%d; broker items=%d (low-conf %d)"
          % (len(pipeline) + len(c3c4), len(personal), len(committee),
             len(unsigned) + len(limayue), len(per_item),
             brief["per_item_broker_scope"]["low_confidence_count"]))


if __name__ == "__main__":
    main()
