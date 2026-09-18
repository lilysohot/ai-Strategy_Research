"""I0A-4 候选金标包 v3（U 第二轮评审四点修正，2026-09-15）。

修正：
1. 页眉/正文分离：剥离页眉声明行后再判正文角色（industry-009 景气一览表、industry-020 报告要点不再误判）；
   覆盖矩阵改用正文判定 + 更完整表格识别，并显式声明"线索非结论"。
2. anchor_hints 全部带 doc_id（query_id+doc_id+seq 唯一定位）；expected 改为 expected_items 结构化数组
   （kind/unit/period/row/col/cell/quote/text），允许一槽拆多条；表格槽强制对照原 PDF 提示。
3. baseline 绑定闭合：formula_7 引用路径修正；57 字段预期资产=pilot_manifest.json（verify_claims_entry 消费
   sample.gold）；客户表 12/12 承认独立非回归入口待构建（micro gold 评分器不含贝特利预期，移除误引）；
   各绑定补运行参数与副作用说明。
4. 校验器分两节（候选模板检查现在跑 / 人工金标冻结检查冻结时跑）；write-once 用 open('x') 独占创建，
   校验先于写入，单次写入；守卫安装 + 运行快照绑定进包。

执行纪律：守卫 i0a4-gold 先装；DSN 仅经 CORPUS_GOLD_DSN 显式传入（543 隔离库）；零模型零子进程。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

REPO = Path(__file__).resolve().parents[3]
IR = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
GUARD_CONFIG = IR / "guards/i0a4-gold.json"
OUT_PATH = IR / "i0a4-candidates-v3-20260915.json"

HEADER_MARK = re.compile(
    r"^.*?(请阅读最后评级说明|请通过合法途径获取|请务必阅读正文之后的|免责声明|分析师声明及).*?$"
)
# 评级词须伴随评级定义结构（"未来 N 个月"/收益率措辞），防止"股东减持风险"等正文误判；
# 纯结构锚（评级体系/评级说明）单独成立。
GENERIC_BODY_MARK = re.compile(
    r"评级说明：|评级体系|投资评级说明|基准指数说明"
    r"|(?:买入|增持|减持|中性|回避)[^。]{0,40}?(?:未来\s*\d+\s*[-~—至]?\s*\d*\s*个月|个月内|的投资收益率)"
)
TABLE_MARK = re.compile(
    r"一览表|续表|涨跌幅|周涨跌|单位：|百万元|资产负债表|利润表|现金流量表|预测表"
)
NUMERIC_COL_ROW = re.compile(r"^\s*\S{1,12}(?:[\s|]+[-+]?[\d,\.]+[%％亿元万亿]?){2,}")
DIM_PATTERNS = {
    "数字": re.compile(r"\d"),
    "单位": re.compile(r"%|％|元|万|亿|\$|美元|吨|GW|GWh|pct|pp|吨"),
    "期间": re.compile(r"20\d{2}[EA]?|[QH][1-4]|上半年|下半年|年初|年末|同比|环比"),
    "否定条件": re.compile(r"未|不|低于|超过|若无|假设|风险|除外|不含"),
    "表格": None,  # 由 TABLE_MARK/NUMERIC_COL_ROW 判定
    "脚注": re.compile(r"注：|注释|脚注|资料来源|数据来源"),
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> NoReturn:
    print(f"I0A-4 候选包生成拒绝执行: {msg}", file=sys.stderr)
    raise SystemExit(2)


def split_header_body(text: str) -> tuple[list[str], str]:
    """剥离页眉声明行（逐行匹配），返回 (header_markers, body)。"""
    headers, body_lines = [], []
    for ln in text.splitlines():
        if ln.strip() and HEADER_MARK.match(ln.strip()):
            headers.append(ln.strip()[:60])
        else:
            body_lines.append(ln)
    return headers, "\n".join(body_lines).strip()


def is_table(body: str) -> bool:
    return bool(TABLE_MARK.search(body) or NUMERIC_COL_ROW.search(body, re.M))


def main() -> None:
    if OUT_PATH.exists():
        fail(f"write-once 冲突：{OUT_PATH.name} 已存在（不覆盖；如需重生成请升版本号）")
    dsn = os.environ.get("CORPUS_GOLD_DSN", "").strip()
    if not dsn:
        fail("环境变量 CORPUS_GOLD_DSN 未设置；隔离库连接串必须显式传入，禁止读 CORPUS_DSN/.env")

    # 守卫先装，再连库（连接目标须命中 allowed_targets）
    from plugins.corpus.preparation import guard

    cfg = guard.install(GUARD_CONFIG)
    from psycopg.conninfo import conninfo_to_dict

    parts = conninfo_to_dict(dsn)
    host = parts.get("host") or "localhost"
    port = int(parts.get("port") or 5432)
    if (host, port) not in {(h, p) for h, p in cfg.allowed_targets}:
        fail(f"目标 {host}:{port} 不在守卫阶段 {cfg.phase} 的 allowed_targets")

    import psycopg

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with psycopg.connect(dsn, connect_timeout=10, autocommit=True, options="-c default_transaction_read_only=on") as conn:
        rows = conn.execute(
            "SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT doc_id, seq, locator, text FROM blocks WHERE doc_id IN ("
            + ",".join(f"'{d}'" for d in sorted({s['db_doc_id'] for s in json.loads((IR / 'i0a2-adjudicated-20260915.json').read_text(encoding='utf-8'))['sources'] if s.get('dev_selection') == 'approved'}))
            + ") ORDER BY doc_id, seq) t"
        ).fetchone()[0]
    blocks: dict[str, dict[int, dict]] = {}
    for row in rows:
        blocks.setdefault(row["doc_id"], {})[int(row["seq"])] = {"locator": row["locator"], "text": row["text"]}

    adj = json.loads((IR / "i0a2-adjudicated-20260915.json").read_text(encoding="utf-8"))
    dev = [s for s in adj["sources"] if s.get("dev_selection") == "approved"]
    doc_scope = {s["db_doc_id"]: s["scope"] for s in dev}
    doc_path = {s["db_doc_id"]: s["path"] for s in dev}
    src_hash = {d: sha256_file(REPO / p) for d, p in doc_path.items()}

    # ── 槽位 v3：页眉/正文分离 + expected_items ──────────────
    sk = list(csv.DictReader(open(REPO / "data/corpus/.audit/c3c4_field_gold_all133_skeleton_20260912.csv", encoding="utf-8")))
    key0 = "\ufeffclaim_gold_id" if "\ufeffclaim_gold_id" in sk[0] else "claim_gold_id"
    slots: list[dict] = []
    slot_bodies: list[tuple[dict, str, str]] = []  # (slot, body, scope) 供矩阵正文级扫描
    for r in sk:
        d = r["doc_id"]
        if d not in doc_scope:
            continue
        seq = int(r["seq"])
        full = blocks[d][seq]["text"]
        headers, body = split_header_body(full)
        seqs = sorted(blocks[d])
        i = seqs.index(seq)
        if not body:
            role, basis = "noise", "剥离页眉后无正文"
        elif (gm := GENERIC_BODY_MARK.search(body)):
            role = "generic_statement"
            basis = f"正文含评级定义/说明措辞：{gm.group(0)[:50]!r}"
        elif len(body) < 120:
            role, basis = "undecidable", "正文过短不足判定"
        else:
            role, basis = "body_evidence_candidate", "含具体数值/事实表述"
        slots.append({
            "gold_slot": r[key0],
            "doc_id": d, "scope": doc_scope[d],
            "source_path": doc_path[d], "source_sha256": src_hash[d],
            "locator_legacy": r["locator"], "page_semantics": "PDF 一页一块：locator=页序，full_text=该页解析文本；表格列关系解析可能丢失，标注表格单元格必须对照原 PDF（按 source_sha256 校验后查看）",
            "char_count": len(full),
            "full_text": full,
            "header_markers": headers,
            "body_role_suggestion": role,
            "role_suggestion_basis": basis,
            "role_suggestion_scope": "仅针对剥离页眉后的正文；同一页可拆多条不同角色预期",
            "annotation_role": None,
            "role_enum": ["body_evidence", "generic_statement", "noise", "undecidable"],
            "expected_items": [],
            "expected_item_spec": {"kind": "value|condition|rating|table_cell|page_ref", "unit": "str|null", "period": "str|null", "row": "str|null", "col": "str|null", "cell": "str|null", "quote": "原文摘录", "text": "人工预期值", "allow_split": "一个槽位可拆多条预期"},
            "must_preserve": None,
            "reviewer": None, "reviewed_at": None,
        })
        slot_bodies.append((slots[-1], body, doc_scope[d]))

    # ── anchor_hints 带 doc_id ───────────────────────────────
    def anchors(d: str, k: int = 3) -> list[dict]:
        return [
            {"doc_id": d, "seq": q, "locator": b["locator"], "head": re.sub(r"\s+", " ", b["text"])[:60], "char_count": len(b["text"])}
            for q, b in sorted(blocks[d].items())[:k]
        ]

    qslots = []
    n = {"company": 0, "industry": 0, "macro": 0}
    for scope in ("company", "industry", "macro"):
        docs = sorted(d for d, s in doc_scope.items() if s == scope)
        for typ, cnt in (("answerable", 8), ("negative", 2)):
            for _ in range(cnt):
                n[scope] += 1
                qslots.append({
                    "query_id": f"{scope}-{n[scope]:03d}", "domain": scope, "query_kind": typ,
                    "question": None, "critical": None,
                    "answer_existence": "no_answer" if typ == "negative" else "answerable",
                    "satisfy_rule": None,
                    "evidence_requirement": None,
                    "relevant_sources": None,
                    "relevant_sources_semantics": "按『存在支持答案的证据』人工判定；与『搜索可能返回相关背景』区分；负例=语料无支持证据≠检索零命中",
                    "anchor_hints": anchors(docs[0]) + (anchors(docs[1], 2) if len(docs) > 1 else []),
                    "human_basis": None, "reviewer": None, "reviewed_at": None,
                })

    # ── 覆盖矩阵（正文判定，线索非结论；bodies 在槽位循环中收集）──
    matrix = {}
    for scope in ("company", "industry", "macro"):
        ss = [(s, b) for s, b, sc in slot_bodies if sc == scope]
        per = {}
        for dim, pat in DIM_PATTERNS.items():
            per[dim] = sum(1 for _, b in ss if (pat.search(b) if pat else is_table(b)))
        matrix[scope] = {"slot_total": len(ss), "per_dim_supported_body_level": per}
    matrix["_status"] = "线索（body 级机器扫描），非覆盖结论；最终覆盖与补槽由 U 判定"
    matrix["_gaps"] = {
        "industry": "正文级扫描后表格维度应不再为 0（景气一览表/续表按表格识别）；槽位仅 3，U 可从块锚点扩槽",
        "macro": "槽位 5；NFP actual/consensus/previous（0/3 旧失败字段）至少一槽覆盖",
    }

    # ── baseline 绑定 v3（闭合到预期资产/运行参数/副作用）────
    manifest = IR / ".." / ".." / ".." / "data" / "corpus"  # placeholder, unused
    pilot = REPO / ".scratch/corpus-evidence-pipeline/pilot_manifest.json"
    vce = REPO / ".scratch/corpus-evidence-pipeline/verify_claims_entry.py"
    baseline = {
        "financial_controlled_recalc_57": {
            "expectation_asset": {"path": str(pilot.relative_to(REPO)), "sha256": sha256_file(pilot),
                                  "content": "samples[*].gold = 逐字段预期（茅台32/广立微15/国信10 结构）；sample.pages 限定页范围"},
            "runnable_entry": {"path": str(vce.relative_to(REPO)), "sha256": sha256_file(vce),
                               "params": "CorpusService.extract_claims(明确源文件, pages)；field_checks/calculations 消费 pilot_manifest gold",
                               "side_effects": "向原库写 corpus_evidence_runs 新行（零模型但非零写）——I0 阶段禁止重跑，非回归重验排 I3-5；本绑定不构成 I0 内的执行授权",
                               "db": "原库 5432"},
            "machine_record": {"path": ".scratch/corpus-evidence-pipeline/claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json",
                               "note": "run_id+fields_passed+formulas（含 expected/tolerance/calculation_id）"},
            "metric_note": "57=三样本冻结字段通过合计；公式 7 归入本节点子项",
            "formula_7": {"case": "茅台公式复算", "expected": "7/7", "asset": "同上 pilot_manifest derive=True 样本 + 机器记录 formulas"},
        },
        "customer_table_12": {
            "expectation_asset": {"status": "frozen_cells_in_semantic_repair_round", "run_id": "0a1dbf39dbfad8428b31eacdd7d5cf8a5fdef250e7df558eb55586690ed4e44f",
                                  "source_anchor": "贝特利 PDF（历史扩大留出 holdout_protected）", "expected": "12 单元格：行、列、原值、单位精确匹配"},
            "runnable_entry": {"status": "待构建", "note": "已定位历史报告≠已具备非回归验收入口；独立复现脚本需从冻结 run 重建，登记为 I3-5 前待办；verify_material_micro_gold.py 为 R2 微金标评分器（r2_material_micro_gold_v1），不含贝特利客户表预期，不作为本项入口（v2 误引已撤销）"},
            "report": "semantic-repair-report.md L15",
        },
        "prose_numbers_3": {
            "expectation_asset": {"note": "光大非农 NFP 正文冻结目标（actual 16.2万/consensus 5.6万 等，质量=review 不得计算）", "source_anchor": "6fc25e24（本批开发材料 macro）"},
            "runnable_entry": {"status": "prose-repair 轮 4 次真实调用 2/2 + semantic-repair 回归 3/3", "side_effects": "含模型调用的历史轮；复跑须另立预算授权", "note": "宏观 0/3 与正文 3/3 均含语义门禁（evidence-pipeline-6）"},
            "report": "spec.md L87 + prose-repair-report.md + semantic-repair-report.md",
        },
        "macro_legacy_fields_0_of_3": {
            "expectation_asset": {"fields": ["actual", "consensus", "previous"], "expected": "0/3，单列不伪装通过", "known_reasons": "华泰『万』不可验证岗位单位；预期指标未统一；中银 basis『同比』≠冻结 YoY（semantic-repair-report L94）"},
            "runnable_entry": {"status": "无通过入口（失败基线保留）；宏观实施 M1-M6 未执行（issues/15/16/17）"},
        },
        "legacy_retrieval_golden": {
            "expectation_asset": {"path": "plugins/corpus/golden.py", "sha256": "e983b3914be4f30a0e59250f22b6ef1b30a04c39a3f681f45323f1550e2cc52b"},
            "runnable_entry": {"status": "待 U 圈定适用范围后同口径重评（I3-5）", "note": "旧 recall 为逐题通过口径，不转移为新索引召回"},
        },
    }

    # ── 执行快照 ─────────────────────────────────────────────
    snapshot = {
        "guard": {"phase": cfg.phase, "config": str(GUARD_CONFIG), "config_sha256": hashlib.sha256(GUARD_CONFIG.read_bytes()).hexdigest()},
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db_target": {"host": host, "port": port, "database": parts.get("dbname"), "note": "凭据不入包"},
        "access_mode": "psycopg 直连（无 docker exec 子进程）；连接级 default_transaction_read_only=on",
        "model_calls": 0, "child_processes": 0,
    }

    # ── 校验（先于写入）─────────────────────────────────────
    errs = validate_template(slots, qslots, matrix, baseline)
    validation = {
        "candidate_template_checks": {"checks": "空字段/重复ID/来源绑定完整/U字段未预填/负例冲突/8+2分配/矩阵加总/基线节点引用存在",
                                      "passed": not errs, "errors": errs,
                                      "body_role_suggestions": {s["gold_slot"]: s["body_role_suggestion"] for s in slots if s["body_role_suggestion"] != "body_evidence_candidate"}},
        "human_gold_freeze_checks": {
            "when": "U 填写完成、写入 source-gold/query-gold.jsonl 前运行（独立脚本，冻结门）",
            "checks": [
                "source-gold：每槽 annotation_role 非空且在枚举内；expected_items 非空且每条 kind/text/quote 齐全；表格类 cell 必填且 quote 与原 PDF 哈希绑定核对",
                "query-gold：question 非空；answerable 必填 satisfy_rule∈{any,all}+evidence_requirement+relevant_sources；negative 必须 satisfy_rule 为空且 relevant_sources 语义为无支持证据；critical 为布尔",
                "一致性：relevant_sources ⊆ admitted 40 ∪ {对应类留出}；query_id/source gold_id 全局唯一；reviewer=U+时间戳齐全",
                "反推禁令：expected/relevant_sources 不得来自任何检索运行输出（记录来源人工依据）",
            ],
        },
    }

    out = {
        "artifact": OUT_PATH.name,
        "task": "I0A-4 候选金标包 v3（U 第二轮评审四点修正落实）",
        "generated_at": snapshot["finished_at"],
        "supersedes": "i0a4-candidates-v2-20260915.json（write-once 保留）",
        "execution_snapshot": snapshot,
        "discipline": {
            "no_model_questions": "question/critical/satisfy_rule/evidence_requirement/relevant_sources 全部由 U 判定",
            "no_answer_derivation": "expected 一律来自人工记录/原文摘录，不引用检索结果；金标仅用于评估，不反哺运行链路",
            "scoring": "每类 8 answerable（召回分母 8）+ 2 negative（单独评分）",
        },
        "format_boundary": {"all_pdf": True, "statement": "6/6 开发材料均 PDF；本批金标验收仅覆盖 PDF 解析路径，MD/DOCX 真实材料不在声明范围（MD 侧仅 P0 茅台 fixture）"},
        "source_gold_candidates": {"count": len(slots), "per_doc": {d: sum(1 for s in slots if s['doc_id'] == d) for d in sorted(doc_scope)}, "slots": slots},
        "block_anchors": {d: {"scope": doc_scope[d], "blocks": anchors(d, 99)} for d in sorted(blocks)},
        "query_gold_slots": qslots,
        "coverage_matrix": matrix,
        "baseline_bindings_v3": baseline,
        "validation": validation,
    }
    with OUT_PATH.open("x", encoding="utf-8") as f:  # 独占创建，绝不覆盖
        f.write(json.dumps(out, ensure_ascii=False, indent=1))
        f.flush()
        os.fsync(f.fileno())
    print("slots:", len(slots), "| queries:", len(qslots), "| blocks:", {d: len(b) for d, b in blocks.items()})
    print("template_checks:", "PASS" if not errs else errs)
    print("body_role_suggestions:", json.dumps(validation["candidate_template_checks"]["body_role_suggestions"], ensure_ascii=False))


def _body_of(s: dict) -> str:
    return s.get("_body", "")


def validate_template(slots: list[dict], qslots: list[dict], matrix: dict, baseline: dict) -> list[str]:
    errs: list[str] = []
    if len({s["gold_slot"] for s in slots}) != len(slots):
        errs.append("slot id 重复")
    if len({q["query_id"] for q in qslots}) != len(qslots):
        errs.append("query id 重复")
    for s in slots:
        if not s["source_sha256"] or len(s["source_sha256"]) != 64:
            errs.append(f"来源哈希缺失: {s['gold_slot']}")
        if not s["full_text"].strip():
            errs.append(f"空全文: {s['gold_slot']}")
        if s["annotation_role"] is not None or s["expected_items"]:
            errs.append(f"U 字段被预填: {s['gold_slot']}")
    for q in qslots:
        if q["question"] is not None or q["relevant_sources"] is not None or q["evidence_requirement"] is not None or q["satisfy_rule"] is not None or q["critical"] is not None:
            errs.append(f"query U 字段被预填: {q['query_id']}")
        if q["query_kind"] == "negative" and q["answer_existence"] != "no_answer":
            errs.append(f"负例冲突: {q['query_id']}")
        if not q["anchor_hints"] or any(("doc_id" not in a or "seq" not in a) for a in q["anchor_hints"]):
            errs.append(f"锚点缺 doc_id/seq: {q['query_id']}")
    per: dict[str, dict[str, int]] = {}
    for q in qslots:
        per.setdefault(q["domain"], {"answerable": 0, "negative": 0})[q["query_kind"]] += 1
    for scope, c in per.items():
        if c != {"answerable": 8, "negative": 2}:
            errs.append(f"{scope} 分配非 8+2: {c}")
    stotal = sum(matrix[k]["slot_total"] for k in ("company", "industry", "macro"))
    if stotal != len(slots):
        errs.append(f"矩阵加总 {stotal} != 槽位 {len(slots)}")
    if matrix["industry"]["per_dim_supported_body_level"]["表格"] == 0:
        errs.append("industry 表格维度仍为 0（正文级表格识别未生效）")
    # baseline 节点引用存在性
    for k in ("financial_controlled_recalc_57", "customer_table_12", "prose_numbers_3", "macro_legacy_fields_0_of_3", "legacy_retrieval_golden"):
        if k not in baseline:
            errs.append(f"baseline 节点缺失: {k}")
    if "formula_7" not in baseline.get("financial_controlled_recalc_57", {}):
        errs.append("formula_7 应为 financial_controlled_recalc_57 子节点")
    return errs


if __name__ == "__main__":
    main()
