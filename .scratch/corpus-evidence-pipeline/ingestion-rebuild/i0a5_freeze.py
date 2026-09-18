"""I0A-5 逻辑契约与开发基线联合冻结门（2026-09-15）。

消费 I0A-4 冻结报告的 inputs/outputs 与 I0A-1..3 产物，重算全部绑定哈希，
形成不可变 M1 快照：i0a5-logic-contract-frozen-v1-20260915.json + 冻结报告。

两个子命令：
- check：只读校验全部前置门并打印重算绑定表（零写）。
- emit --confirmed-by TEXT：check 全过后 write-once 生成 M1 快照与冻结报告；
  任何输出已存在即拒绝（重冻结升版本文件名，不覆盖）。

前置门（少一即拒；全部以当前磁盘哈希重算）：
1. I0A-1：findings 绑定哈希一致；复核报告 decision=通过。
2. I0A-2：73 条终态（admitted 40 / excluded 6 / excluded_from_active 27；开发材料 6=三类各 2；
   留出保护 3）；冻结时点重测（i0a5-doclist-recount）零增删改且核心记录在库未变。
3. I0A-3：policy frozen v1；验证 0 矛盾且三类计数与终态一致；6 项表达式齐；与契约判定次序一致。
4. I0A-4：冻结门报告 inputs/outputs 与磁盘一致；source 23 / query 30（每域 8+2、关键题、
   any/all、negative 空规则）；23 槽原 PDF 冻结时点哈希复核；baseline-bindings 无 pending。
5. I1-8 守卫绑定：run3 反例指纹（12/12 拒绝）与当前守卫文件一致；i1.json 保持 fail-closed 预置。
6. 草案保留：i0a5-logic-contract-draft.json frozen=false，契约六节齐（冻结不改草案）。

隔离纪律：守卫 i0a5-freeze（deny_all 零网络、零模型、零子进程）先装再做任何读取；
冻结时点表计数重测属于独立只读步骤，由 i0a2_doclist.py 在 i0-inventory 守卫下先行执行并落盘，
本门不连任何数据库（allowed_targets=[]）。输出 write-once，已存在即拒绝。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

REPO = Path(__file__).resolve().parents[3]
IR = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
GUARD_CONFIG = IR / "guards/i0a5-freeze.json"

INV = IR / "i0-inventory.json"
FINDINGS = IR / "i0a1-inventory-findings.json"
REVIEW1 = IR / "i0a1-review.json"
MANIFEST = IR / "dev-manifest.json"
QUEUE = IR / "review-queue.json"
BRIEF = IR / "i0a2-review-brief.json"
OLD_DOCLIST = IR / "i0a2-doclist-findings.json"
ADJ = IR / "i0a2-adjudicated-20260915.json"
RECOUNT = IR / "i0a5-doclist-recount-20260915.json"
POLICY = IR / "admission-policy.json"
VERIF = IR / "i0a3-policy-verification.json"
PKG = IR / "i0a4-candidates-v3-20260915.json"
WORKING = IR / "i0a4-labeling-working.json"
REP4 = IR / "i0a4-freeze-report-20260915.json"
SRC_FROZEN = IR / "source-gold-frozen.jsonl"
QRY_FROZEN = IR / "query-gold-frozen.jsonl"
BASELINE = IR / "baseline-bindings.json"
DRAFT = IR / "i0a5-logic-contract-draft.json"
GUARD_I1 = IR / "guards/i1.json"
GUARD_INV = IR / "guards/i0-inventory.json"
GUARD_PY = REPO / "plugins/corpus/preparation/guard.py"
GUARD_PYTEST = REPO / "plugins/corpus/preparation/guard_pytest.py"
GUARD_INIT = REPO / "plugins/corpus/preparation/__init__.py"
GUARD_TESTS = REPO / "tests/test_corpus_preparation_guard.py"
V2REPORT = IR / "i0-guard-report-v2.json"
RUN3 = IR / "audits/2026-09-15-status/guard-counterexamples-run3.json"

OUT_CONTRACT = IR / "i0a5-logic-contract-frozen-v1-20260915.json"
OUT_REPORT = IR / "i0a5-freeze-report-20260915.json"

DOMAINS = ("company", "industry", "macro")
ROLE_ENUM = {"body_evidence", "generic_statement", "noise", "undecidable"}
CONTRACT_SECTIONS = (
    "decide_admission", "citation_authority", "report_publication_date",
    "coverage_axes", "revision_model", "job_state_machine",
)

BINDING_FILES: list[tuple[str, Path]] = [
    ("i0a1_inventory", INV),
    ("i0a1_findings", FINDINGS),
    ("i0a1_review", REVIEW1),
    ("i0a2_dev_manifest", MANIFEST),
    ("i0a2_review_queue", QUEUE),
    ("i0a2_review_brief", BRIEF),
    ("i0a2_doclist_findings", OLD_DOCLIST),
    ("i0a2_adjudicated", ADJ),
    ("i0a2_doclist_recount", RECOUNT),
    ("i0a3_admission_policy", POLICY),
    ("i0a3_policy_verification", VERIF),
    ("i0a4_candidates_v3", PKG),
    ("i0a4_labeling_working", WORKING),
    ("i0a4_freeze_report", REP4),
    ("i0a4_source_gold_frozen", SRC_FROZEN),
    ("i0a4_query_gold_frozen", QRY_FROZEN),
    ("i0a4_baseline_bindings", BASELINE),
    ("i1_guard_config", GUARD_I1),
    ("i0_guard_config_inventory", GUARD_INV),
    ("i1_guard_impl", GUARD_PY),
    ("i1_guard_pytest", GUARD_PYTEST),
    ("i1_guard_init", GUARD_INIT),
    ("i1_guard_tests", GUARD_TESTS),
    ("i0_guard_report_v2", V2REPORT),
    ("i0_guard_counterexamples_run3", RUN3),
]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> NoReturn:
    print(f"I0A-5 冻结门拒绝: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _install_guard() -> None:
    from plugins.corpus.preparation import guard

    guard.install(GUARD_CONFIG)


def _load_jsonl_gold(path: Path, expect_lines: int, errs: list[str]) -> list[dict]:
    records = _jsonl(path)
    if len(records) != expect_lines:
        errs.append(f"{path.name}: 记录数 {len(records)} != {expect_lines}")
        return []
    return records


def _verify() -> tuple[list[str], list[str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """全部门校验 + 重算绑定哈希。返回 (errors, notes, checks, bindings, draft)。"""
    errs: list[str] = []
    notes: list[str] = []
    checks: dict[str, Any] = {}

    # ── 0. 绑定文件存在性（先查再算哈希） ──
    for name, p in BINDING_FILES:
        if not p.exists():
            errs.append(f"绑定文件缺失 {name}: {p.relative_to(REPO)}")
    if errs:
        return errs, notes, checks, {}, {}
    bindings = {name: {"path": str(p.relative_to(REPO)), "sha256": sha256_file(p)} for name, p in BINDING_FILES}

    # ── 1. I0A-1 ──
    inv = _load(INV)
    if inv.get("evidence", {}).get("findings_sha256") != bindings["i0a1_findings"]["sha256"]:
        errs.append("I0A-1 inventory.evidence.findings_sha256 与 findings 当前哈希不一致")
    if "复核通过" not in _load(REVIEW1).get("decision", ""):
        errs.append("I0A-1 复核报告 decision 未标记通过")
    notes.append("I0A-1 守卫配置版本漂移（51b28f22→d3025d52，allowed_targets 未变）为复核已说明项，沿用 i0a1-review.json")

    # ── 2. I0A-2 ──
    adj = _load(ADJ)
    srcs = adj.get("sources", [])
    if len(srcs) != 73:
        errs.append(f"I0A-2 终态条数 {len(srcs)} != 73")
    dec = Counter(s.get("decision") for s in srcs)
    if dec != {"admitted": 40, "excluded": 6, "excluded_from_active": 27}:
        errs.append(f"I0A-2 决策分布异常: {dict(dec)}")
    if not all(s.get("decision_by", "").startswith("U") and s.get("decided_at") for s in srcs):
        errs.append("I0A-2 存在缺 decision_by=U 或 decided_at 的终态记录")
    if not all(str(s.get("decision_note") or "").strip() for s in srcs):
        errs.append("I0A-2 存在缺 decision_note 的终态记录")
    admitted = [s for s in srcs if s.get("decision") == "admitted"]
    dev = [s for s in srcs if s.get("dev_selection") == "approved"]
    hold = [s for s in srcs if s.get("holdout_protected")]
    dev_scopes = Counter(s.get("scope") for s in dev)
    if len(dev) != 6 or dev_scopes != {"company": 2, "industry": 2, "macro": 2}:
        errs.append(f"I0A-2 开发材料非三类各 2：{len(dev)} {dict(dev_scopes)}")
    if len(hold) != 3:
        errs.append(f"I0A-2 留出保护 {len(hold)} != 3")
    if not all(s.get("scope") in DOMAINS for s in admitted):
        errs.append("I0A-2 admitted 存在 scope 缺失或超出 company/industry/macro")
    if not {s["db_doc_id"] for s in dev} <= {s["db_doc_id"] for s in admitted}:
        errs.append("I0A-2 开发材料不全是已准入来源")
    if adj.get("inputs", {}).get("dev-manifest.json") != bindings["i0a2_dev_manifest"]["sha256"]:
        errs.append("I0A-2 终态登记 dev-manifest 绑定哈希与当前不一致")

    rc = _load(RECOUNT)
    old = _load(OLD_DOCLIST)
    if rc.get("errors"):
        errs.append(f"冻结时点重测含错误: {rc['errors']}")
    if len(rc.get("documents", [])) != 89 or rc.get("counts_by_status") != {"empty": 18, "ok": 71}:
        errs.append(f"冻结时点重测计数异常: {len(rc.get('documents', []))} {rc.get('counts_by_status')}")
    if (rc.get("target", {}).get("host"), rc.get("target", {}).get("port")) != ("127.0.0.1", 5432):
        errs.append(f"冻结时点重测目标异常: {rc.get('target')}")
    if rc.get("guard", {}).get("phase") != "i0-inventory":
        errs.append(f"冻结时点重测未在 i0-inventory 守卫下执行: {rc.get('guard')}")
    o = {d["doc_id"]: d for d in old["documents"]}
    n = {d["doc_id"]: d for d in rc["documents"]}
    added, removed = sorted(set(n) - set(o)), sorted(set(o) - set(n))
    changed = [k for k in sorted(set(o) & set(n)) if o[k] != n[k]]
    if added or removed or changed:
        errs.append(f"冻结时点重测出现增量/缺失/变更: added={added} removed={removed} changed={changed}")
    core_ids = sorted({s["db_doc_id"] for s in srcs if s["db_doc_id"]
                       and (s.get("decision") == "admitted" or s.get("dev_selection") == "approved"
                            or s.get("holdout_protected"))})
    missing = [k for k in core_ids if k not in n]
    if missing:
        errs.append(f"核心登记记录不在冻结时点重测中: {missing}")
    hash_changed = [k for k in core_ids if o.get(k, {}).get("content_hash") != n.get(k, {}).get("content_hash")]
    if hash_changed:
        errs.append(f"核心登记记录 content_hash 变化: {hash_changed}")
    if _iso(rc["observed_at"]) <= _iso(_load(REP4)["generated_at"]):
        errs.append("冻结时点重测早于 I0A-4 冻结门完成时间（顺序不符）")
    checks["i0a2"] = {
        "adjudicated": 73, "admitted": 40, "excluded": 6, "excluded_from_active": 27,
        "dev": 6, "dev_scopes": dict(dev_scopes), "holdout": 3,
        "recount": {"observed_at": rc["observed_at"], "documents": len(rc["documents"]),
                    "by_status": rc["counts_by_status"],
                    "delta": {"added": len(added), "removed": len(removed), "changed": len(changed)}},
    }

    # ─ 3. I0A-3 ──
    pol = _load(POLICY)
    draft = _load(DRAFT)
    if pol.get("frozen") is not True or pol.get("policy_rev") != "v1-20260915":
        errs.append(f"I0A-3 policy 未冻结或版本异常: frozen={pol.get('frozen')} rev={pol.get('policy_rev')}")
    if pol.get("auto_decision", {}).get("enabled") is not False:
        errs.append("I0A-3 auto_decision 未保持禁用")
    feats = {f.get("feature_id"): f for f in pol.get("features", [])}
    expect_feats = {"title_type_marker", "byline_institution", "heading_hierarchy",
                    "speaker_turns", "qa_markers", "transcript_declaration"}
    if not expect_feats <= set(feats):
        errs.append(f"I0A-3 特征缺失: {sorted(expect_feats - set(feats))}")
    if not all(str(f.get("match_expression") or "").strip() and f.get("scan_limit") for f in feats.values()):
        errs.append("I0A-3 存在空表达式或缺失扫描上限的特征")
    ver = _load(VERIF)
    bd = ver.get("verification_results", {}).get("by_decision", {})
    if ver.get("verification_results", {}).get("contradictions") != []:
        errs.append(f"I0A-3 验证存在矛盾: {ver['verification_results'].get('contradictions')}")
    if ver.get("verification_results", {}).get("snapshot_minutes_positives") != 0:
        errs.append("I0A-3 验证快照纪要正例数与登记不符")
    if ver.get("inputs", {}).get("i0a2-adjudicated-20260915.json") != bindings["i0a2_adjudicated"]["sha256"]:
        errs.append("I0A-3 验证输入终态哈希与当前不一致")
    counts_ok = (bd.get("admitted") == {"broker": 38, "absent": 2}
                 and bd.get("excluded") == {"pipeline": 5, "broker": 1}
                 and bd.get("excluded_from_active") == {"personal": 17, "absent": 4, "committee": 6})
    sums_ok = (sum(bd.get("admitted", {}).values()) == 40
               and sum(bd.get("excluded", {}).values()) == 6
               and sum(bd.get("excluded_from_active", {}).values()) == 27)
    if not counts_ok or not sums_ok:
        errs.append(f"I0A-3 验证计数与终态不一致: {bd}")
    if "I1 合成夹具" not in json.dumps(pol.get("positive_negative_examples", {}), ensure_ascii=False):
        errs.append("I0A-3 缺正例待办登记（I1 合成夹具）")
    if pol.get("interface", {}).get("signature") != draft.get("contract", {}).get("decide_admission", {}).get("signature"):
        errs.append("I0A-3 政策接口签名与本契约不一致")
    pol_text = json.dumps(pol, ensure_ascii=False)
    for tok in ("in_scope", "excluded_by_policy", "review_required"):
        if tok not in pol_text:
            errs.append(f"I0A-3 政策输出枚举缺 {tok}")
    for tok in draft.get("contract", {}).get("decide_admission", {}).get("output_enums", {}).get("reason_codes_at_least", []):
        if tok not in pol_text:
            errs.append(f"I0A-3 政策 reason_codes 缺契约要求的 {tok}")
    draft_pol_hash = ver.get("inputs", {}).get("admission-policy.json (draft-1)")
    if draft_pol_hash != bindings["i0a3_admission_policy"]["sha256"]:
        notes.append(f"I0A-3 验证运行在 draft-1（{draft_pol_hash}）上，冻结 v1（{bindings['i0a3_admission_policy']['sha256']}）"
                     "与 draft-1 的字节差未留存；以 U 批准（freeze_note）+ expression_status 与验证结果计数一致作替代证据")
    else:
        notes.append("I0A-3 验证任务标签为 draft-1，但其输入哈希与冻结 v1（policy_rev=v1-20260915）当前字节一致："
                     "验证证据即绑定冻结版字节，无版本漂移")
    checks["i0a3"] = {"policy_rev": pol.get("policy_rev"), "features": len(feats),
                      "contradictions": len(ver["verification_results"]["contradictions"]),
                      "by_decision_totals": {"admitted": sum(bd.get("admitted", {}).values()),
                                             "excluded": sum(bd.get("excluded", {}).values()),
                                             "excluded_from_active": sum(bd.get("excluded_from_active", {}).values())}}

    # ── 4. I0A-4 ──
    rep = _load(REP4)
    for key, path in (("working", WORKING), ("adjudicated_sha256", ADJ)):
        rec = rep["inputs"]["working"] if key == "working" else {"sha256": rep["inputs"]["adjudicated_sha256"]}
        if rec["sha256"] != sha256_file(path):
            errs.append(f"I0A-4 冻结报告输入 {key} 哈希与当前不一致")
    if rep["inputs"]["package_ref"]["sha256"] != bindings["i0a4_candidates_v3"]["sha256"]:
        errs.append("I0A-4 冻结报告候选包哈希与当前不一致")
    if rep["outputs"]["source-gold-frozen.jsonl"]["sha256"] != bindings["i0a4_source_gold_frozen"]["sha256"]:
        errs.append("I0A-4 冻结报告 source-gold 输出哈希与当前不一致")
    if rep["outputs"]["query-gold-frozen.jsonl"]["sha256"] != bindings["i0a4_query_gold_frozen"]["sha256"]:
        errs.append("I0A-4 冻结报告 query-gold 输出哈希与当前不一致")
    if rep.get("checks", {}).get("label_slots") != 23 or rep.get("checks", {}).get("query_slots") != 30 \
            or rep.get("checks", {}).get("errors") != []:
        errs.append(f"I0A-4 冻结报告 checks 异常: {rep.get('checks')}")

    sg = _load_jsonl_gold(SRC_FROZEN, 23, errs)
    roles = Counter(r.get("annotation_role") for r in sg)
    if roles != {"body_evidence": 20, "generic_statement": 3}:
        errs.append(f"I0A-4 source-gold 角色构成异常: {dict(roles)}")
    pathmap = {s["db_doc_id"]: s["path"] for s in srcs if s["db_doc_id"]}
    pdf_ok = 0
    for r in sg:
        if r.get("annotation_role") not in ROLE_ENUM:
            errs.append(f"{r.get('gold_id')}: annotation_role 非法")
        if not str(r.get("human_basis") or "").strip() or not str(r.get("reviewer") or "").strip():
            errs.append(f"{r.get('gold_id')}: human_basis/reviewer 缺失")
        try:
            _iso(r.get("reviewed_at"))
        except (ValueError, TypeError):
            errs.append(f"{r.get('gold_id')}: reviewed_at 非法")
        items = r.get("expected_items")
        if r.get("annotation_role") == "body_evidence" and not items:
            errs.append(f"{r.get('gold_id')}: body_evidence 缺 expected_items")
        if r.get("annotation_role") != "body_evidence" and items:
            errs.append(f"{r.get('gold_id')}: 非 body_evidence 不应携带 expected_items")
        pdf = REPO / pathmap.get(r.get("source_id"), "")
        if not pdf.is_file() or sha256_file(pdf) != r.get("source_sha256"):
            errs.append(f"{r.get('gold_id')}: 原 PDF 冻结时点哈希复核失败")
        else:
            pdf_ok += 1

    qg = _load_jsonl_gold(QRY_FROZEN, 30, errs)
    per_domain = Counter(q.get("domain") for q in qg)
    per = Counter((q.get("domain"), q.get("query_kind")) for q in qg)
    for d in DOMAINS:
        if per.get((d, "answerable")) != 8 or per.get((d, "negative")) != 2:
            errs.append(f"I0A-4 {d} 分配非 8+2: {per.get((d, 'answerable'))}+{per.get((d, 'negative'))}")
    if not all(str(q.get("question") or "").strip() for q in qg):
        errs.append("I0A-4 存在空题干")
    if not all(isinstance(q.get("critical"), bool) for q in qg):
        errs.append("I0A-4 critical 非布尔")
    crit = Counter(q["domain"] for q in qg if q.get("critical"))
    if any(crit.get(d, 0) < 1 for d in DOMAINS):
        errs.append(f"I0A-4 存在无关键题的域: {dict(crit)}")
    sat = Counter(q.get("satisfy_rule") for q in qg if q.get("query_kind") == "answerable")
    if set(sat) != {"any", "all"}:
        errs.append(f"I0A-4 answerable satisfy_rule 未覆盖 any/all: {dict(sat)}")
    for q in qg:
        if q.get("query_kind") == "negative":
            if q.get("satisfy_rule") is not None or q.get("relevant_sources") != []:
                errs.append(f"{q.get('query_id')}: negative 须 satisfy_rule 空且 relevant_sources=[]")
        else:
            rs = q.get("relevant_sources")
            if not rs or not set(rs) <= {s["db_doc_id"] for s in dev}:
                errs.append(f"{q.get('query_id')}: relevant_sources 为空或超出 6 份开发材料")
            if not str(q.get("evidence_requirement") or "").strip():
                errs.append(f"{q.get('query_id')}: evidence_requirement 缺失")
    checks["i0a4"] = {"source_records": len(sg), "source_roles": dict(roles),
                      "query_records": len(qg), "query_per_domain": dict(per_domain),
                      "critical": dict(crit), "satisfy_rule": dict(sat),
                      "pdf_hash_recheck": f"{pdf_ok}/{len(sg)} 通过"}

    bb = _load(BASELINE)
    bb_list = bb.get("bindings", [])
    if len(bb_list) != 7:
        errs.append(f"baseline-bindings 类目 {len(bb_list)} != 7")
    pending = [b.get("category") for b in bb_list if "pending" in str(b.get("status") or "")]
    if pending:
        errs.append(f"baseline-bindings 仍有 pending: {pending}")

    # ── 5. I1-8 守卫绑定 ──
    run3 = _load(RUN3)
    if run3.get("passed") != 12 or run3.get("failed") != 0:
        errs.append(f"run3 反例未全拒绝: passed={run3.get('passed')} failed={run3.get('failed')}")
    drift = [f for f, h in run3.get("fingerprints", {}).items()
             if not (REPO / f).is_file() or sha256_file(REPO / f) != h]
    if drift:
        errs.append(f"守卫指纹漂移: {drift}")
    g1 = _load(GUARD_I1)
    if g1.get("network", {}).get("mode") != "deny_all" or g1.get("network", {}).get("allowed_targets") != [] \
            or g1.get("sources", {}).get("read_roots") != []:
        errs.append("i1.json 未保持 fail-closed 预置（deny_all / 空 read_roots）")
    checks["guard"] = {"run3": f"{run3.get('passed')}/{run3.get('passed', 0) + run3.get('failed', 0)} 拒绝",
                       "fingerprints": f"{len(run3.get('fingerprints', {}))} 文件与当前一致"}

    # ── 6. 草案保留（冻结不覆盖草案） ──
    if draft.get("frozen") is not False:
        errs.append("i0a5-logic-contract-draft.json 应为 frozen=false（冻结不得覆盖草案）")
    if set(draft.get("contract", {})) != set(CONTRACT_SECTIONS):
        errs.append(f"草案契约章节异常: {sorted(draft.get('contract', {}))}")

    return errs, notes, checks, bindings, draft


def _development_baseline(checks: dict[str, Any]) -> dict[str, Any]:
    return {
        "note": "M1 开发基线（冻结）：本契约 + I0A-2 来源终态与开发分母 + I0A-4 金标/负例 + I1-8 守卫绑定；"
                "物理候选仍待 I0-C，不以本快照冻结物理布局",
        "sources": {"adjudicated_total": 73, "admitted_research_report": 40, "excluded": 6,
                    "excluded_from_active": 27, "holdout_protected": 3, "dev_approved": 6,
                    "dev_scopes": checks["i0a2"]["dev_scopes"]},
        "denominator_freeze": {"recount": str(RECOUNT.relative_to(REPO)), **checks["i0a2"]["recount"]},
        "gold": {"source": {"records": checks["i0a4"]["source_records"], "roles": checks["i0a4"]["source_roles"]},
                 "query": {"records": checks["i0a4"]["query_records"],
                           "per_domain": checks["i0a4"]["query_per_domain"],
                           "critical": checks["i0a4"]["critical"], "satisfy_rule": checks["i0a4"]["satisfy_rule"]}},
        "guard_binding": {"run3": checks["guard"]["run3"], "fingerprints": checks["guard"]["fingerprints"],
                          "i1_config": "deny_all；read_roots 空（待 I1 启动时回填实际来源清单并重验）"},
        "i1_implications": [
            "I1-1 contract 内存数据模型须逐一实现本契约枚举/判定次序/必填字段，非法组合在 Interface 校验拒绝",
            "I1-5 admission 表驱动用例由冻结后的 admission-policy 与 I0A-2 终态生成；"
            "speaker_turns/qa_markers/transcript_declaration 正例由 I1 合成夹具提供（登记待办）",
            "I1 全部测试不构造真实 PG/模型客户端；I1-8 守卫绑定与来源清单回填先于任何测试收集",
        ],
    }


def _carried_items() -> list[dict[str, Any]]:
    return [
        {"item": "旧检索题（legacy_retrieval_golden）适用范围与同口径重评", "route": "I3-5（U 圈定范围后）", "blocking_m1": False},
        {"item": "旧人工审核导出权威版本（.audit 88 工件）与 docs/chinese_docs 遗留表归属", "route": "I0-C", "blocking_m1": False},
        {"item": "I0-C 清理清单（DB 21 条删除 + 磁盘 1 文件 + 37 ADS 残留）",
         "route": "前置 M2+I0-C 冻结+I4 停写窗口+U 执行签认；本阶段零执行", "blocking_m1": False},
        {"item": "宿主侧外部写入者手段（单 superuser 角色）", "route": "I4 停写窗口需 U 提供", "blocking_m1": False},
        {"item": "I1-8 实际 I1 来源清单回填与拒绝路径验证（模型客户端陷阱、子进程继承）", "route": "I1 启动首项", "blocking_m1": False},
        {"item": "物理布局候选（复用/新建/迁移字段）", "route": "I0-C-1 裁决；契约枚举与判定次序不变", "blocking_m1": False},
    ]


def _print_bindings(bindings: dict[str, Any]) -> None:
    print("重算绑定（25 件）：")
    for name, rec in bindings.items():
        print(f"  {name:26s} sha256={rec['sha256'][:16]}…  {rec['path']}")


def check() -> None:
    _install_guard()
    errs, notes, checks, bindings, _ = _verify()
    if errs:
        print(f"I0A-5 冻结门 check 未通过（{len(errs)} 项）：", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(2)
    print("I0A-5 冻结门 check 通过（只读，未写任何输出）。")
    _print_bindings(bindings)
    print(f"  I0A-2 冻结时点重测: {checks['i0a2']['recount']}")
    print(f"  I0A-4 金标: source {checks['i0a4']['source_records']} / query {checks['i0a4']['query_records']}"
          f"；PDF 复核 {checks['i0a4']['pdf_hash_recheck']}")
    print(f"  I1-8 守卫: run3 {checks['guard']['run3']}；指纹 {checks['guard']['fingerprints']}")
    if notes:
        print("已说明限制（写入冻结报告）：")
        for n in notes:
            print(f"  · {n}")
    print("下一步：U 联合确认后运行 emit --confirmed-by \"<确认语句>\" 生成 M1 快照（write-once）。")


def emit(confirmed_by: str) -> None:
    _install_guard()
    errs, notes, checks, bindings, draft = _verify()
    if errs:
        print(f"I0A-5 冻结门未通过，拒绝 emit（{len(errs)} 项）：", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(2)
    started = datetime.now(timezone.utc)
    for p in (OUT_CONTRACT, OUT_REPORT):
        if p.exists():
            fail(f"{p.name} 已存在（write-once；重冻结请升版本文件名，不覆盖）")

    def write_once(p: Path, text: str) -> str:
        with p.open("x", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        return sha256_file(p)

    contract = {
        "artifact": OUT_CONTRACT.name,
        "task": "I0A-5 逻辑契约与开发基线联合冻结（frozen v1；M1 阶段快照）",
        "date": "2026-09-15",
        "frozen": True,
        "freeze_basis": {
            "confirmed_by": confirmed_by,
            "gate": "i0a5_freeze.py check 全过；本件与冻结报告 write-once 独占创建",
            "preconditions_verified": [
                "I0A-1 复核通过（i0a1-review.json）+ findings 绑定哈希一致",
                "I0A-2 73 条终态（U 裁决 2026-09-15）：admitted 40 / excluded 6 / excluded_from_active 27；"
                "开发材料 6（company/industry/macro 各 2）；留出保护 3；冻结时点重测 89=71+18 零增删改、核心记录在库未变",
                "I0A-3 admission-policy frozen v1-20260915：6 项表达式、验证 0 矛盾、三类计数与终态一致，自动准入保持禁用",
                "I0A-4 冻结门通过：source-gold 23 条 / query-gold 30 条（每域 8+2、含关键题与 any/all、无答案负例 6）；"
                "23 槽原 PDF 冻结时点哈希复核通过",
                "I1-8 守卫绑定：run3 反例 12/12 拒绝、7 文件指纹与当前一致；i1.json 保持 deny_all/read_roots 空 fail-closed 预置",
                "baseline-bindings 7 类全部绑定（无 pending_locate_and_hash）",
            ],
        },
        "supersedes": {"draft": "i0a5-logic-contract-draft.json（frozen=false，保留不改；草案只汇集与绑定，不新增语义）"},
        "authority": draft["authority"],
        "freeze_gate": {
            "script": "i0a5_freeze.py", "script_sha256": sha256_file(Path(__file__)),
            "guard_config": str(GUARD_CONFIG.relative_to(REPO)), "config_sha256": sha256_file(GUARD_CONFIG),
            "network_mode": "deny_all（零连接）", "model_calls": 0, "child_processes": 0,
        },
        "bindings": bindings,
        "contract": draft["contract"],
        "development_baseline": _development_baseline(checks),
        "carried_items": _carried_items(),
        "discipline": "冻结件不可变；发现错误升版本重冻结（frozen-v2…），不得覆盖；草案保留；"
                      "金标仅用于评估，不反哺运行链路；I0-C 若调整物理布局，仅权威映射整体迁移，"
                      "逻辑契约枚举与判定次序不变；本批次零模型、零数据库写入。",
    }
    contract_sha = write_once(OUT_CONTRACT, json.dumps(contract, ensure_ascii=False, indent=1) + "\n")

    report = {
        "artifact": OUT_REPORT.name,
        "task": "I0A-5 联合冻结门通过记录（M1 阶段快照）",
        "generated_at": started.isoformat(timespec="seconds"),
        "confirmed_by": confirmed_by,
        "guard": {"phase": "i0a5-freeze", "config": str(GUARD_CONFIG), "config_sha256": sha256_file(GUARD_CONFIG),
                  "network_mode": "deny_all（零连接；冻结时点重测由 i0-inventory 守卫下只读步骤先行完成）",
                  "model_calls": 0, "child_processes": 0},
        "script_sha256": sha256_file(Path(__file__)),
        "inputs": bindings,
        "checks": {**checks, "errors": []},
        "documented_limitations": notes,
        "outputs": {OUT_CONTRACT.name: {"sha256": contract_sha, "frozen": True}},
        "discipline": "冻结件不可变；发现错误升版本重冻结（frozen-v2…），不得覆盖；金标仅用于评估，"
                      "不反哺运行链路；下一步 I1（I1-8 先执行）。",
    }
    report_sha = write_once(OUT_REPORT, json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print("I0A-5 联合冻结完成（M1 阶段快照）：")
    print(f"  {OUT_CONTRACT.name} sha256={contract_sha[:16]}…")
    print(f"  {OUT_REPORT.name} sha256={report_sha[:16]}…")
    print("下一步：回填执行台账；M1 达成后开 I1（I1-8 守卫绑定与来源清单先于测试收集）。")


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("用法: check | emit --confirmed-by TEXT")
        return
    if argv[0] == "check":
        check()
        return
    if argv[0] == "emit":
        confirmed = None
        it = iter(argv[1:])
        for a in it:
            if a == "--confirmed-by":
                confirmed = next(it, None)
        if not str(confirmed or "").strip():
            fail("emit 须提供 --confirmed-by（记录 U 的联合确认语句；不得代签）")
        emit(confirmed)
        return
    fail(f"未知子命令: {argv[0]!r}")


if __name__ == "__main__":
    main()