"""I0A-4 候选包 v2（U 评审意见逐项落实，2026-09-15）。

改进点：
1. 摘录→完整块全文（PDF 一页一块，块全文=该页解析文本）+ 相邻块导航 + 原 PDF 路径与 SHA-256。
2. 定位补齐：source_sha256、locator 语义声明（旧块仅导航，原文正确性以原文件哈希为准）。
3. annotation_role 四分类 + 机器 role_suggestion（通用评级说明/免责声明 → generic_statement 嫌疑，供防误归属反例）。
4. query 槽去预填 relevant_sources；拆 critical/answer_existence/satisfy_rule 三字段；8+2 分配；证据要求字段。
5. 覆盖矩阵（数字/单位/期间/否定条件/表格/脚注/噪声 × 三类，机器扫描支撑度，最终由 U 判）。
6. 旧基线绑定到具体用例/预期/运行入口，不再只绑报告数字。
7. 格式边界声明：6/6 PDF，MD/DOCX 真实材料验收不在本批范围。
8. 内置确定性校验器并运行。
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
IR = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUG = REPO / ".scratch/corpus-evidence-pipeline"

GENERIC_MARK = re.compile(r"评级说明|评级体系|分析师声明|免责声明|投资评级说明|行业投资评级|公司投资评级")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def psql(sql: str) -> list[str]:
    r = subprocess.run(
        ["docker", "exec", "corpus-db", "psql", "-U", "postgres", "-d", "i0b2_verify_postgres", "-At", "-F", "|", "-c", sql],
        capture_output=True, text=True,
    )
    if r.returncode:
        raise RuntimeError(r.stderr[:300])
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def main() -> None:
    adj = json.loads((IR / "i0a2-adjudicated-20260915.json").read_text(encoding="utf-8"))
    dev_by_sid = {s["source_id"]: s for s in adj["sources"] if s.get("dev_selection") == "approved"}
    doc_scope = {s["db_doc_id"]: s["scope"] for s in dev_by_sid.values()}
    doc_path = {s["db_doc_id"]: s["path"] for s in dev_by_sid.values()}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 全块拉取（一次查询，JSON 聚合避免换行/分隔符破坏行边界）
    raw = subprocess.run(
        ["docker", "exec", "corpus-db", "psql", "-U", "postgres", "-d", "i0b2_verify_postgres", "-At", "-c",
         "SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT doc_id, seq, locator, text FROM blocks WHERE doc_id IN ("
         + ",".join(f"'{d}'" for d in sorted(doc_scope)) + ") ORDER BY doc_id, seq) t"],
        capture_output=True, text=True,
    )
    if raw.returncode:
        raise RuntimeError(raw.stderr[:300])
    blocks = {}
    for row in json.loads(raw.stdout):
        blocks.setdefault(row["doc_id"], {})[int(row["seq"])] = {"locator": row["locator"], "text": row["text"]}

    # 来源文件哈希
    src_hash = {d: sha256_file(REPO / p) for d, p in doc_path.items()}

    # ── 1) source-gold 槽位 v2 ──────────────────────────────
    sk = list(csv.DictReader(open(REPO / "data/corpus/.audit/c3c4_field_gold_all133_skeleton_20260912.csv", encoding="utf-8")))
    key0 = "\ufeffclaim_gold_id" if "\ufeffclaim_gold_id" in sk[0] else "claim_gold_id"
    slots = []
    for r in sk:
        d = r["doc_id"]
        if d not in doc_scope:
            continue
        seq = int(r["seq"])
        full = blocks[d][seq]["text"]
        seqs = sorted(blocks[d])
        i = seqs.index(seq)
        role = "generic_statement" if GENERIC_MARK.search(full) else ("undecidable" if len(full) < 200 else "body_evidence_candidate")
        slots.append({
            "gold_slot": r[key0],
            "doc_id": d,
            "scope": doc_scope[d],
            "source_path": doc_path[d],
            "source_sha256": src_hash[d],
            "locator_legacy": r["locator"],
            "locator_semantics": "旧解析器页序号，仅作导航；原文正确性以原 PDF + source_sha256 为准（本批 6/6 为 PDF，一页一块，块全文=该页解析文本）",
            "char_count": len(full),
            "full_text": full,
            "context_nav": {"prev_seq": seqs[i - 1] if i else None, "next_seq": seqs[i + 1] if i + 1 < len(seqs) else None},
            "role_suggestion": role,
            "role_suggestion_basis": "含评级体系/声明类措辞" if role == "generic_statement" else ("块过短不足判定" if role == "undecidable" else "含具体数值/事实表述"),
            "annotation_role": None,
            "role_enum": ["body_evidence", "generic_statement", "noise", "undecidable"],
            "expected": None,
            "expected_fields_enum": ["value", "condition", "rating", "table_cell", "page_ref"],
            "must_preserve": None,
            "reviewer": None,
            "reviewed_at": None,
        })

    # ── 2) query-gold 槽位 v2（8 answerable + 2 negative 每类）────────
    blocks_head = {
        d: [{"seq": q, "locator": b["locator"], "head": re.sub(r"\s+", " ", b["text"])[:60], "char_count": len(b["text"])} for q, b in sorted(blocks[d].items())]
        for d in blocks
    }
    qslots = []
    n = {"company": 0, "industry": 0, "macro": 0}
    for scope in ("company", "industry", "macro"):
        docs = sorted(d for d, s in doc_scope.items() if s == scope)
        for typ, cnt in (("answerable", 8), ("negative", 2)):
            for _ in range(cnt):
                n[scope] += 1
                qslots.append({
                    "query_id": f"{scope}-{n[scope]:03d}",
                    "domain": scope,
                    "query_kind": typ,
                    "question": None,
                    "critical": None,
                    "critical_note": "关键题标志独立记录；关键题可同时是跨文档 all 题",
                    "answer_existence": "no_answer" if typ == "negative" else "answerable",
                    "satisfy_rule": None,
                    "satisfy_rule_enum": ["any", "all"],
                    "satisfy_rule_note": "仅 answerable 填 any|all；negative 必须留空",
                    "evidence_requirement": None,
                    "evidence_requirement_note": "U 填：支持答案的证据块/页/单元格范围；与『搜索可能返回的相关背景』区分",
                    "relevant_sources": None,
                    "relevant_sources_note": "U 按证据存在性判定，不预填；negative 语义=语料中不存在支持该答案的证据，检索仍可能命中相关背景，负例单独评分不计入有答案分母",
                    "anchor_hints": blocks_head.get(docs[0], [])[:3] + blocks_head.get(docs[1] if len(docs) > 1 else docs[0], [])[:2],
                    "human_basis": None,
                    "reviewer": None,
                    "reviewed_at": None,
                })

    # ── 3) 覆盖矩阵（机器扫描支撑度）─────────────────────────
    def scan_slot(s: dict) -> dict:
        t = s["full_text"]
        return {
            "数字": bool(re.search(r"\d", t)),
            "单位": bool(re.search(r"%|元|万|亿|\$|美元|吨|GW|GWh|pct|pp", t)),
            "期间": bool(re.search(r"20\d{2}[EA]?|[QH][1-4]|上半年|下半年|年初|年末", t)),
            "否定条件": bool(re.search(r"未|不|低于|超过|若无|假设|风险|。*(除外|不含)", t)),
            "表格": bool(re.search(r"预测表|资产负债|利润表|现金流量|单位：|百万元", t)),
            "脚注": bool(re.search(r"注：|注释|脚注|资料来源", t)),
            "噪声嫌疑": s["role_suggestion"] in ("generic_statement",),
        }

    matrix = {}
    for scope in ("company", "industry", "macro"):
        ss = [s for s in slots if s["scope"] == scope]
        matrix[scope] = {
            "slot_total": len(ss),
            "per_dim_supported": {dim: sum(1 for s in ss if scan_slot(s)[dim]) for dim in ["数字", "单位", "期间", "否定条件", "表格", "脚注", "噪声嫌疑"]},
        }
    matrix["_gaps"] = {
        "industry": "槽位仅 3（长江 2 + 华福 1），表格/脚注等维度支撑度低；建议 U 从 25+11 块锚点扩槽或声明本批 industry 覆盖以数字/期间为主",
        "macro": "槽位 5；宏观 0/3 旧失败字段（NFP actual/consensus/previous）应至少一槽覆盖",
        "note": "矩阵为机器扫描支撑度，最终覆盖判定与补槽由 U 决定；不强求均分",
    }

    # ── 4) baseline 绑定 v2（具体用例/预期/运行入口）──────────
    baseline = {
        "financial_controlled_recalc_57": {
            "cases": [
                {"case": "茅台财务预测页冻结字段", "expected": "32 字段", "source_anchor": "2026-08-16_6f14cc14（本批开发材料 company）", "page": "财务预测表页"},
                {"case": "广立微财务表冻结字段", "expected": "15 字段", "source_anchor": "库内广立微文档（非本批 73）", "page": "财务表页"},
                {"case": "国信茅台留出页冻结字段", "expected": "10 字段", "source_anchor": "国信茅台=历史留出（holdout_protected）"},
            ],
            "formula_7": {"case": "茅台公式复算", "expected": "7/7", "source_anchor": "2026-08-16_6f14cc14"},
            "runnable_entry": ".scratch/corpus-evidence-pipeline/verify_claims_entry.py",
            "machine_record": "claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json",
            "report": "claims-entry-report.md L21-29",
            "metric_note": "57=冻结字段通过数；468 条为正式取证事实数（不全部是金标字段）",
        },
        "customer_table_12": {
            "cases": [{"case": "贝特利客户表冻结单元格召回", "expected": "12/12 行、列、原值、单位精确匹配", "source_anchor": "贝特利=历史扩大留出（holdout_protected）"}],
            "runnable_entry": "semantic-repair 定点修复轮（最终客户表 run 0a1dbf39dbfad8428b31eacdd7d5cf8a5fdef250e7df558eb55586690ed4e44f）；离线核查 verify_material_micro_gold.py",
            "report": "semantic-repair-report.md L15",
        },
        "prose_numbers_3": {
            "cases": [{"case": "正文数值冻结目标", "expected": "3/3", "source_anchor": "光大非农 NFP 正文（本批开发材料 macro）；扩大留出轮曾 2/3 后修复"}],
            "runnable_entry": "prose-repair 修复轮验证（4 次真实调用 2/2）+ semantic-repair 回归",
            "report": "spec.md L87 + semantic-repair-report.md",
        },
        "macro_legacy_fields_0_of_3": {
            "cases": [{"case": "宏观规范字段 actual/consensus/previous", "expected": "0/3，单列不伪装为通过", "source_anchor": "光大非农 NFP（本批开发材料 macro）"}],
            "runnable_entry": "无现行通过入口（失败基线保留）；宏观实施 M1-M6 未执行（issues/15/16/17）",
            "report": "spec.md L87",
        },
        "legacy_retrieval_golden": {
            "cases": [{"case": "旧检索 golden 题（plugins/corpus/golden.py）", "expected": "待 U 圈定适用范围后同口径重评", "source_anchor": "不转移为新索引标准集合召回"}],
            "runnable_entry": "plugins/corpus/golden.py（sha256 e983b391…）",
        },
    }

    # ── 5) 格式边界 ─────────────────────────────────────────
    format_boundary = {
        "dev_materials_formats": {p.split("_", 1)[1][:40]: Path(p).suffix for p in doc_path.values()},
        "all_pdf": True,
        "statement": "本批 6/6 开发材料均为 PDF：金标验收声明仅覆盖 PDF 解析路径；DOCX/MD 真实材料验收不在本批范围、不得据此声称通过",
        "md_side_note": "MD 侧仅存 p0-fixtures/2026-08-16_600519.SH.md（P0 历史用例 fixture），不构成 MD 通用验收",
    }

    out = {
        "artifact": "i0a4-candidates-v2-20260915.json",
        "task": "I0A-4 候选金标材料 v2（U 评审 6+2 项意见落实；工程侧完善后交 U 确认）",
        "generated_at": now,
        "supersedes": "i0a4-candidates-20260915.json（保留不覆盖，write-once）",
        "discipline": {
            "no_model_questions": "question/critical/satisfy_rule/evidence_requirement/relevant_sources 全部由 U 判定填写",
            "no_answer_derivation": "expected 类字段一律来自人工记录/原文摘录，不引用检索结果；金标仅用于评估，不得反哺运行链路抽取边界",
            "scoring": "每类 8 answerable（召回分母=8）+ 2 negative（单独评分，不抬高通过率）",
        },
        "format_boundary": format_boundary,
        "source_gold_candidates": {"count": len(slots), "per_doc": {d: sum(1 for s in slots if s['doc_id'] == d) for d in sorted(doc_scope)}, "slots": slots},
        "block_anchors": {d: {"scope": doc_scope[d], "blocks": blocks_head[d]} for d in sorted(blocks)},
        "query_gold_slots": qslots,
        "coverage_matrix": matrix,
        "baseline_bindings_v2": baseline,
    }
    (IR / "i0a4-candidates-v2-20260915.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 6) 确定性校验器 ─────────────────────────────────────
    errs: list[str] = []
    ids = [s["gold_slot"] for s in slots]
    if len(ids) != len(set(ids)):
        errs.append("slot id 重复")
    if len({q["query_id"] for q in qslots}) != len(qslots):
        errs.append("query id 重复")
    for s in slots:
        if not s["full_text"].strip():
            errs.append(f"空全文: {s['gold_slot']}")
        if not (REPO / s["source_path"]).exists() or len(s["source_sha256"]) != 64:
            errs.append(f"来源绑定无效: {s['gold_slot']}")
        if s["annotation_role"] is not None or s["expected"] is not None:
            errs.append(f"U 字段被预填: {s['gold_slot']}")
        if s["annotation_role"] not in (None,) or s["role_suggestion"] not in {"body_evidence_candidate", "generic_statement", "undecidable"}:
            errs.append(f"role_suggestion 非法: {s['gold_slot']}")
        if s["locator_semantics"] == "" or s["source_sha256"] == "":
            errs.append(f"定位绑定缺失: {s['gold_slot']}")
    for q in qslots:
        if q["question"] is not None or q["relevant_sources"] is not None or q["evidence_requirement"] is not None:
            errs.append(f"query U 字段被预填: {q['query_id']}")
        if q["query_kind"] == "negative" and q["satisfy_rule"] is not None:
            errs.append(f"负例 satisfy_rule 冲突: {q['query_id']}")
        if q["query_kind"] == "answerable" and not q["anchor_hints"]:
            errs.append(f"answerable 缺锚点: {q['query_id']}")
        if q["answer_existence"] not in ("answerable", "no_answer"):
            errs.append(f"answer_existence 非法: {q['query_id']}")
    per_class = {}
    for q in qslots:
        per_class.setdefault(q["domain"], {"answerable": 0, "negative": 0})
        per_class[q["domain"]][q["query_kind"]] += 1
    for scope, c in per_class.items():
        if c != {"answerable": 8, "negative": 2}:
            errs.append(f"{scope} 分配非 8+2: {c}")
    msum = sum(m["slot_total"] for k, m in matrix.items() if k.startswith(("company", "industry", "macro")))
    if msum != len(slots):
        errs.append(f"覆盖矩阵加总 {msum} != 槽位 {len(slots)}")
    validation = {
        "validator": "deterministic（空字段/重复ID/无效定位/负例冲突/U字段预填/分配/矩阵加总）",
        "checks_passed": not errs,
        "errors": errs,
        "slot_role_suggestions": {s["gold_slot"]: s["role_suggestion"] for s in slots if s["role_suggestion"] != "body_evidence_candidate"},
        "per_class_distribution": per_class,
    }
    out["validation"] = validation
    (IR / "i0a4-candidates-v2-20260915.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("slots:", len(slots), "| queries:", len(qslots), "| blocks:", {d: len(b) for d, b in blocks.items()})
    print("validation:", json.dumps(validation, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
