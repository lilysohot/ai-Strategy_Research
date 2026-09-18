"""I0A-4 人工金标冻结门（2026-09-15，U 指示：先定向修正隔离与冻结契约，再开展人工标注）。

两阶段契约（候选模板检查已在 i0a4_candidates_v3.py 生成时通过，v3 包 write-once 保留）：
- make-working：从 v3 候选包派生人工标注工作文件（write-once），绑定包 sha256；
  工作文件可反复编辑，v3 包本身不可写。
- check：冻结门。校验人工填写后的工作文件，全部通过才 emit 冻结三件套
  （source-gold-frozen.jsonl / query-gold-frozen.jsonl / i0a4-freeze-report-<日期>.json），
  一律 open('x') 独占创建单次写入；任何输出已存在即拒绝，要求升版本而非覆盖。

冻结门检查（对 v3 包 validation.human_gold_freeze_checks 的定向细化）：
- 绑定：工作文件 package_ref.sha256 必须等于 v3 包当前哈希；槽位/题目 ID 集合与包完全一致；
  doc_id/source_sha256/answer_existence/domain/query_kind 不得篡改；每份原 PDF 磁盘哈希复核。
- source 槽：annotation_role ∈ 枚举；body_evidence 须有非空 expected_items（kind 枚举、text/quote
  齐全、quote 经空白归一后必须是该槽 full_text 的子串、table_cell 必填 cell）；
  generic_statement/noise/undecidable 须 expected_items=[]（分类声明不含数值预期）。
- query 槽：answerable 必填 question + satisfy_rule∈{any,all} + evidence_requirement +
  relevant_sources（⊆ 6 份开发材料，超出即拒——30 题从开发材料出题，留出文档不得进入分母）；
  negative 须 satisfy_rule 为空且 relevant_sources=[]（语义=语料无支持证据≠检索零命中）；
  critical 必须布尔。
- 人工依据：每槽/题 human_basis 非空（反推禁令的自证），reviewer/reviewed_at 齐全。

隔离纪律：守卫 i0a4-freeze（deny_all 零网络、零模型、零子进程）先装再做任何读取；
冻结门不连任何数据库（allowed_targets=[]），与生成阶段（仅 543）相比进一步收紧。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

REPO = Path(__file__).resolve().parents[3]
IR = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
GUARD_CONFIG = IR / "guards/i0a4-freeze.json"
PACKAGE_PATH = IR / "i0a4-candidates-v3-20260915.json"
ADJ_PATH = IR / "i0a2-adjudicated-20260915.json"
WORKING_PATH = IR / "i0a4-labeling-working.json"
OUT_SOURCE = "source-gold-frozen.jsonl"
OUT_QUERY = "query-gold-frozen.jsonl"

ROLE_ENUM = {"body_evidence", "generic_statement", "noise", "undecidable"}
ITEM_KIND_ENUM = {"value", "condition", "rating", "table_cell", "page_ref"}
QUERY_DOMAIN_ENUM = {"company", "industry", "macro"}
SATISFY_ENUM = {"any", "all"}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> NoReturn:
    print(f"冻结门拒绝: {msg}", file=sys.stderr)
    raise SystemExit(2)


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _load_package() -> dict:
    pkg = json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))
    pkg_sha = sha256_file(PACKAGE_PATH)
    return pkg, pkg_sha


def _install_guard() -> None:
    from plugins.corpus.preparation import guard

    guard.install(GUARD_CONFIG)


def make_working() -> None:
    if WORKING_PATH.exists():
        fail(f"{WORKING_PATH.name} 已存在（write-once；重派生请改名或手工保留副本）")
    _install_guard()
    pkg, pkg_sha = _load_package()

    slots: list[dict] = []
    for s in pkg["source_gold_candidates"]["slots"]:
        slots.append({
            "gold_slot": s["gold_slot"], "doc_id": s["doc_id"], "scope": s["scope"],
            "source_path": s["source_path"], "source_sha256": s["source_sha256"],
            "locator_page": s["locator_legacy"], "header_markers": s["header_markers"],
            "full_text": s["full_text"],
            "annotation_role": None, "expected_items": [], "must_preserve": None,
            "human_basis": None, "reviewer": None, "reviewed_at": None,
        })
    queries: list[dict] = []
    for q in pkg["query_gold_slots"]:
        queries.append({
            "query_id": q["query_id"], "domain": q["domain"], "query_kind": q["query_kind"],
            "answer_existence": q["answer_existence"],
            "question": None, "critical": None, "satisfy_rule": None,
            "evidence_requirement": None, "relevant_sources": None,
            "human_basis": None, "reviewer": None, "reviewed_at": None,
        })
    out = {
        "artifact": WORKING_PATH.name,
        "purpose": "人工标注工作文件（U 可反复编辑）；冻结门 check 按本文件校验后 emit 不可变冻结件；v3 候选包不可写",
        "package_ref": {"artifact": PACKAGE_PATH.name, "sha256": pkg_sha},
        "instructions": {
            "role_enum": sorted(ROLE_ENUM),
            "role_note": "判定对象=剥离页眉后的正文；同一页可拆多条不同角色预期（expected_items allow_split）",
            "expected_item_spec": {"kind": "value|condition|rating|table_cell|page_ref", "unit": "str|null",
                                   "period": "str|null", "row": "str|null", "col": "str|null", "cell": "str|null",
                                   "quote": "原文摘录（须为该槽 full_text 的子串，冻结门强校验）",
                                   "text": "人工预期值"},
            "table_rule": "表格单元格必须对照原 PDF（按 source_sha256 校验后打开 data/corpus 下文件）核对行列关系",
            "negative_rule": "negative 题 satisfy_rule 留空、relevant_sources=[]；语义=语料无支持证据，不是检索零命中",
            "relevant_sources_rule": "answerable 只能引用 6 份开发材料 doc_id（超出即拒）；留出文档不进分母",
            "anti_derivation": "human_basis 必填：记录人工依据（对照原文/外部事实），不得引用任何检索或模型输出",
            "reviewer": "填 U 的标识；reviewed_at 填 ISO 时间戳",
        },
        "label_slots": slots,
        "query_slots": queries,
    }
    with WORKING_PATH.open("x", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=1))
        f.flush()
    print(f"working: {WORKING_PATH.name} | slots={len(slots)} queries={len(queries)} | package sha256={pkg_sha[:16]}…")
    print("下一步：U 填写后运行 check（冻结门）。")


def _check_slot(sl: dict, pkg_slot: dict, doc_path: dict[str, str], errs: list[str]) -> None:
    gid = sl.get("gold_slot")
    if gid not in {p["gold_slot"] for p in [pkg_slot]}:
        return  # 集合一致性在外层统一检查
    if sl.get("doc_id") != pkg_slot["doc_id"] or sl.get("source_sha256") != pkg_slot["source_sha256"]:
        errs.append(f"{gid}: doc_id/source_sha256 与 v3 包不一致（篡改或错位）")
        return
    pdf = REPO / sl["source_path"]
    if not pdf.exists() or sha256_file(pdf) != sl["source_sha256"]:
        errs.append(f"{gid}: 原 PDF 磁盘哈希复核失败")
    role = sl.get("annotation_role")
    if role not in ROLE_ENUM:
        errs.append(f"{gid}: annotation_role 非法: {role!r}")
    if not (sl.get("human_basis") or "").strip():
        errs.append(f"{gid}: human_basis 必填")
    if not (sl.get("reviewer") or "").strip():
        errs.append(f"{gid}: reviewer 必填")
    try:
        datetime.fromisoformat(str(sl.get("reviewed_at") or "").replace("Z", "+00:00"))
    except ValueError:
        errs.append(f"{gid}: reviewed_at 非法: {sl.get('reviewed_at')!r}")
    items = sl.get("expected_items")
    if role == "body_evidence":
        if not isinstance(items, list) or not items:
            errs.append(f"{gid}: body_evidence 须有非空 expected_items")
            return
        pkg_full = norm_ws(pkg_slot["full_text"])
        for i, it in enumerate(items):
            tag = f"{gid}#item{i}"
            if not isinstance(it, dict) or it.get("kind") not in ITEM_KIND_ENUM:
                errs.append(f"{tag}: kind 非法")
                continue
            if not str(it.get("text") or "").strip():
                errs.append(f"{tag}: text 必填")
            quote = str(it.get("quote") or "")
            if not quote.strip():
                errs.append(f"{tag}: quote 必填")
            elif norm_ws(quote) not in pkg_full:
                errs.append(f"{tag}: quote 不是该槽 full_text 子串（空白归一后）")
            if it.get("kind") == "table_cell" and not str(it.get("cell") or "").strip():
                errs.append(f"{tag}: table_cell 必填 cell")
    elif role in ROLE_ENUM and (items is None or items == []):
        pass
    elif role in ROLE_ENUM:
        errs.append(f"{gid}: {role} 不应携带 expected_items（须为 []）")


def _check_query(q: dict, pkg_q: dict, dev_docs: set[str], errs: list[str]) -> None:
    qid = q.get("query_id")
    if q.get("domain") != pkg_q["domain"] or q.get("query_kind") != pkg_q["query_kind"] \
            or q.get("answer_existence") != pkg_q["answer_existence"]:
        errs.append(f"{qid}: domain/query_kind/answer_existence 与 v3 包不一致")
        return
    if not str(q.get("question") or "").strip():
        errs.append(f"{qid}: question 必填")
    if not isinstance(q.get("critical"), bool):
        errs.append(f"{qid}: critical 必须布尔")
    if not (q.get("human_basis") or "").strip():
        errs.append(f"{qid}: human_basis 必填")
    if not (q.get("reviewer") or "").strip():
        errs.append(f"{qid}: reviewer 必填")
    try:
        datetime.fromisoformat(str(q.get("reviewed_at") or "").replace("Z", "+00:00"))
    except ValueError:
        errs.append(f"{qid}: reviewed_at 非法")
    rs = q.get("relevant_sources")
    sr = q.get("satisfy_rule")
    if q["query_kind"] == "negative":
        if sr is not None:
            errs.append(f"{qid}: negative 须 satisfy_rule 为空")
        if rs not in (None, []):
            errs.append(f"{qid}: negative 须 relevant_sources=[]")
        return
    if sr not in SATISFY_ENUM:
        errs.append(f"{qid}: answerable 须 satisfy_rule∈{{any,all}}")
    if not str(q.get("evidence_requirement") or "").strip():
        errs.append(f"{qid}: answerable 须 evidence_requirement 非空")
    if not isinstance(rs, list) or not rs:
        errs.append(f"{qid}: answerable 须 relevant_sources 非空列表")
        return
    bad = [d for d in rs if d not in dev_docs]
    if bad:
        errs.append(f"{qid}: relevant_sources 超出 6 份开发材料: {bad}")


def check(working: Path, emit_dir: Path) -> None:
    if not working.exists():
        fail(f"工作文件不存在: {working}")
    _install_guard()
    pkg, pkg_sha = _load_package()
    wf = json.loads(working.read_text(encoding="utf-8"))
    if wf.get("package_ref", {}).get("sha256") != pkg_sha:
        fail("工作文件 package_ref.sha256 与 v3 包当前哈希不符（包不可写；工作文件须从当前包派生）")

    adj = json.loads(ADJ_PATH.read_text(encoding="utf-8"))
    dev_docs = {s["db_doc_id"] for s in adj["sources"] if s.get("dev_selection") == "approved"}
    doc_path = {s["db_doc_id"]: s["path"] for s in adj["sources"]}

    pkg_slots = {s["gold_slot"]: s for s in pkg["source_gold_candidates"]["slots"]}
    pkg_queries = {q["query_id"]: q for q in pkg["query_gold_slots"]}
    errs: list[str] = []

    wf_slots = {s.get("gold_slot"): s for s in wf.get("label_slots", [])}
    if set(wf_slots) != set(pkg_slots):
        errs.append(f"槽位集合不一致：缺失 {sorted(set(pkg_slots) - set(wf_slots))} 多出 {sorted(set(wf_slots) - set(pkg_slots))}")
    for gid, s in wf_slots.items():
        if gid in pkg_slots:
            _check_slot(s, pkg_slots[gid], doc_path, errs)

    wf_queries = {q.get("query_id"): q for q in wf.get("query_slots", [])}
    if set(wf_queries) != set(pkg_queries):
        errs.append(f"题目集合不一致：缺失 {sorted(set(pkg_queries) - set(wf_queries))} 多出 {sorted(set(wf_queries) - set(pkg_queries))}")
    per: dict[str, dict[str, int]] = {}
    for qid, q in wf_queries.items():
        if qid in pkg_queries:
            _check_query(q, pkg_queries[qid], dev_docs, errs)
            per.setdefault(q.get("domain"), {}).setdefault(q.get("query_kind"), 0)
            per[q.get("domain")][q.get("query_kind")] = per[q.get("domain")].get(q.get("query_kind"), 0) + 1
    for dom in QUERY_DOMAIN_ENUM:
        if per.get(dom, {}) != {"answerable": 8, "negative": 2}:
            errs.append(f"{dom} 分配非 8+2: {per.get(dom)}")

    if errs:
        print(f"冻结门未通过（{len(errs)} 项）：", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(2)

    # ── emit：全部通过才写；三件套均 open('x')，先查存在性再单次写入 ──
    started = datetime.now(timezone.utc)
    src_out, qry_out = emit_dir / OUT_SOURCE, emit_dir / OUT_QUERY
    rep_out = emit_dir / f"i0a4-freeze-report-{started:%Y%m%d}.json"
    for p in (src_out, qry_out, rep_out):
        if p.exists():
            fail(f"{p.name} 已存在（write-once；重冻结请升版本文件名，不覆盖）")

    pkg_ref = {"artifact": PACKAGE_PATH.name, "sha256": pkg_sha}
    src_records = []
    for s in wf["label_slots"]:
        src_records.append({
            "gold_id": s["gold_slot"], "source_id": s["doc_id"], "source_sha256": s["source_sha256"],
            "annotation_role": s["annotation_role"], "locator": {"page": s.get("locator_page")},
            "expected_items": s["expected_items"], "must_preserve": s.get("must_preserve"),
            "human_basis": s["human_basis"], "reviewer": s["reviewer"], "reviewed_at": s["reviewed_at"],
            "package_ref": pkg_ref,
        })
    qry_records = []
    for q in wf["query_slots"]:
        qry_records.append({
            "query_id": q["query_id"], "domain": q["domain"], "query_kind": q["query_kind"],
            "answer_existence": q["answer_existence"], "question": q["question"], "critical": q["critical"],
            "satisfy_rule": q["satisfy_rule"], "evidence_requirement": q["evidence_requirement"],
            "relevant_sources": q["relevant_sources"], "human_basis": q["human_basis"],
            "reviewer": q["reviewer"], "reviewed_at": q["reviewed_at"], "package_ref": pkg_ref,
        })

    def write_once(p: Path, text: str) -> str:
        with p.open("x", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        return hashlib.sha256(p.read_bytes()).hexdigest()

    src_sha = write_once(src_out, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in src_records))
    qry_sha = write_once(qry_out, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in qry_records))
    report = {
        "artifact": rep_out.name,
        "task": "I0A-4 人工金标冻结门通过记录",
        "generated_at": started.isoformat(timespec="seconds"),
        "guard": {"phase": "i0a4-freeze-gate", "config": str(GUARD_CONFIG),
                  "config_sha256": hashlib.sha256(GUARD_CONFIG.read_bytes()).hexdigest(),
                  "network_mode": "deny_all（零连接）", "model_calls": 0, "child_processes": 0},
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "inputs": {"working": {"path": str(working.relative_to(REPO)), "sha256": sha256_file(working)},
                   "package_ref": pkg_ref, "adjudicated_sha256": sha256_file(ADJ_PATH)},
        "checks": {"label_slots": len(src_records), "query_slots": len(qry_records),
                   "pdf_hash_recheck": "全部通过", "quote_substring": "空白归一后强校验通过",
                   "errors": []},
        "outputs": {OUT_SOURCE: {"lines": len(src_records), "sha256": src_sha},
                    OUT_QUERY: {"lines": len(qry_records), "sha256": qry_sha}},
        "discipline": "冻结件不可变；发现错误升版本重冻结（frozen-v2…），不得覆盖；金标仅用于评估，不反哺运行链路",
    }
    rep_sha = write_once(rep_out, json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(f"冻结门通过：source {len(src_records)} 条 / query {len(qry_records)} 条")
    print(f"  {src_out.name} sha256={src_sha[:16]}…")
    print(f"  {qry_out.name} sha256={qry_sha[:16]}…")
    print(f"  {rep_out.name} sha256={rep_sha[:16]}…")
    print("下一步：I0A-5 重算哈希联合冻结（消费本报告 inputs/outputs）。")


def main() -> None:
    argv = [a for a in sys.argv[1:]]
    if argv and argv[0] == "make-working":
        make_working()
        return
    working, emit_dir = WORKING_PATH, IR
    it = iter(argv)
    for a in it:
        if a == "--working":
            working = Path(REPO / next(it))
        elif a == "--emit-dir":
            emit_dir = Path(REPO / next(it))
        elif a in ("-h", "--help"):
            print("用法: make-working | check [--working PATH] [--emit-dir DIR]")
            return
    check(working, emit_dir)


if __name__ == "__main__":
    main()
