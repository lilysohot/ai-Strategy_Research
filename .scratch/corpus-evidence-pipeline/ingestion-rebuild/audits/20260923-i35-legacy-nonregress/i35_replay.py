"""I3-5 开发非回归复跑（旧检索 golden / 财务 / 公式 / 客户表 / 正文 / 宏观 / 负控 / 审批契约门）。

纪律：
- 零模型（全程不构造 LLM 客户端，prose 预算=0）。
- 原库（5432/postgres）**零写入**：只 load 冻结 run 与只读检索；财务复验走
  ``build_evidence_run`` 库级等价路径（不落库）。与冻结契约
  （verify_claims_entry.py 向原库写 corpus_evidence_runs 新行）相比是更收敛的偏差，
  原因：I2-7 后 canonical ``extract_claims`` 改由 corpus_units 投影，而 pilot 三份源
  （e034bdac/b6beb6ee/高盛）不在 i0a2 批准开发集，无法合法入库；偏差在结果 JSON 与
  README 中如实登记，不宣称等同契约执行。
- 留出不读原文：guards/i3.json forbidden_roots 六份（含贝特利/国信茅台/中银/华泰/天风）
  一律不打开文件；客户表 12 格按绑定口径"从冻结 run 重建"复验；国信茅台 10 格登记
  held_out_not_run_in_dev（I3-7 口径）。
- 不得删旧失败题：宏观 0/3 失败基线原样保留单列；golden 逐题口径（含 require_all），
  O6 按 r27 冻结排除，其余 19 题无 skip 机制。

用法：uv run python i35_replay.py（仓库根目录执行）
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
CEP = REPO / ".scratch/corpus-evidence-pipeline"
ING = CEP / "ingestion-rebuild"
AUDIT = ING / "audits/20260923-i35-legacy-nonregress"
CORPUS_ROOT = REPO / "data/corpus"

OLD_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
MACRO_RUN_ID = "552942996489beb4f1f44b66d2ab944a48b1d5b9ff2e81ef59b6c61c71c65fbf"
CUSTOMER_RUN_ID = "0a1dbf39dbfad8428b31eacdd7d5cf8a5fdef250e7df558eb55586690ed4e44f"
CUSTOMER_REPORT = (
    ING / "../semantic-repair-runs/report-d46896495f658c635e3aca9bf35db4282e826c22a5c42dfbec2fdbe952d4d7b2.json"
).resolve()

EXPECTED_HASHES = {
    "pilot_manifest.json": "691581a5d6285b4259a698c47898abf92fa54c7066bdde4d3ca0ffe80c2f5e4f",
    "plugins/corpus/golden.py": "e983b3914be4f30a0e59250f22b6ef1b30a04c39a3f681f45323f1550e2cc52b",
    "verify_claims_entry.py": "e2c52d9e47b43bdd80e233ff002063e4cb4468f4752ebc26398b634a6430d391",
    "claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json": None,  # 内容寻址，文件名即哈希
    "data/corpus/.audit/c1_full84_doc_kind_review_20260912.csv": (
        "d69bbb1d49081ab8c27f10ad3dda141f099411b39598f27fa95be56c2d2ac396"
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm_number(text: str) -> str:
    """r27 冻结规范化：去千分位逗号 → 去前导/尾随零 → 统一负号 → 再判等。"""
    t = (text or "").strip().replace(",", "").replace(" ", "")
    if not t:
        return t
    sign = ""
    if t.startswith(("+", "-")):
        sign = "-" if t[0] == "-" else ""
        t = t[1:]
    if "." in t:
        head, tail = t.split(".", 1)
        head = head.lstrip("0") or "0"
        tail = tail.rstrip("0")
        t = f"{head}.{tail}" if tail else head
    else:
        t = t.lstrip("0") or "0"
    t = t.rstrip(".")
    return sign + t


def check_hashes() -> dict[str, object]:
    out: dict[str, object] = {}
    for rel, expected in EXPECTED_HASHES.items():
        if rel.startswith(("plugins/", "data/")):
            path = REPO / rel
        else:
            path = CEP / rel
        if rel.startswith("claims-entry-"):
            actual = path.name.split("claims-entry-")[1].removesuffix(".json")
        else:
            actual = sha256(path)
        ok = expected is None or actual == expected
        out[rel] = {"sha256": actual, "expected": expected, "match": ok}
        if not ok:
            raise SystemExit(f"资产哈希失配：{rel}: {actual} != {expected}")
    return out


def guard_forbidden() -> list[str]:
    guard = json.loads((ING / "guards/i3.json").read_text(encoding="utf-8"))
    return list(guard["sources"]["forbidden_roots"])


def assert_not_forbidden(paths: list[Path], forbidden: list[str]) -> None:
    for path in paths:
        rel = path.resolve().relative_to(REPO).as_posix()
        if rel in forbidden:
            raise SystemExit(f"拒绝：{rel} 在守卫留出清单，开发期不得读原文")


# ── 财务 / 公式 / 负控（库级等价路径，零写库） ────────────────────────────


def financial_recalc(forbidden: list[str]) -> dict[str, object]:
    from plugins.corpus.evidence_pipeline import build_evidence_run
    from scripts.corpus_evidence_pilot import calculations, field_checks

    manifest = json.loads((CEP / "pilot_manifest.json").read_text(encoding="utf-8"))
    samples: dict[str, object] = {}
    financial_passed = 0
    for sample in manifest["samples"]:
        name = sample["name"]
        if name == "macro_prose":
            # prose 重抽取需模型预算（未授权）→ 冻结 2 例由冻结 run 只读复验，见 macro_frozen()。
            samples[name] = {"status": "not_run_pending_budget", "note": "r27：重抽取须另立预算授权；冻结 2 例走冻结 run 复验"}
            continue
        if name == "guosen_maotai_holdout":
            samples[name] = {"status": "held_out_not_run_in_dev", "note": "r27：国信茅台 bbba671e 10 格为守卫留出，I3-7 口径"}
            continue
        paths = list(CORPUS_ROOT.glob(sample["pattern"]))
        if len(paths) != 1:
            raise SystemExit(f"sample {name} 解析到 {len(paths)} 个文件")
        assert_not_forbidden(paths, forbidden)
        run = build_evidence_run(paths[0], pages=tuple(sample["pages"]))
        run.verify_identity()
        checks = field_checks(run, sample)
        passed = sum(bool(c["passed"]) for c in checks)
        result: dict[str, object] = {
            "field_passed": passed,
            "field_total": len(checks),
            "failed_fields": [
                {k: c[k] for k in ("row", "column", "expected", "unit", "actual")}
                for c in checks
                if not c["passed"]
            ],
        }
        if name == "maotai_financial_tables":
            formulas = calculations(run)
            result["formulas_passed"] = sum(1 for f in formulas if f["passed"])
            result["formulas_total"] = len(formulas)
            result["formulas_detail"] = [
                {k: f[k] for k in ("formula", "passed", "expected", "value", "tolerance") if k in f}
                for f in formulas
            ]
            financial_passed += passed + result["formulas_passed"]
        else:
            financial_passed += passed
        if sample.get("expect_unknown"):
            result["negative_control_passed"] = any(
                p.status == "unknown" for p in run.document.packets
            )
        samples[name] = result
    return {
        "scope": "maotai 32 字段 + 公式 7 + guangli 15 字段 + 高盛负控（库级等价路径）",
        "financial_plus_formulas_passed": financial_passed,
        "target_dev_scope": 47 + 7,
        "samples": samples,
    }


# ── 客户表 12 格（冻结 run 只读复验） ────────────────────────────────────


def customer_table_12() -> dict[str, object]:
    import psycopg

    report = json.loads(CUSTOMER_REPORT.read_text(encoding="utf-8"))
    sample = next(s for s in report["manifest"]["samples"] if s["name"] == "beiteli_customer_table")
    gold = sample["gold"]
    with psycopg.connect(OLD_DSN, connect_timeout=5) as conn:
        row = conn.execute(
            "select payload from corpus_evidence_runs where run_id = %s", (CUSTOMER_RUN_ID,)
        ).fetchone()
    if row is None:
        raise SystemExit("冻结客户表 run 不在库")
    facts = row[0]["facts"]
    cells = []
    for cell in gold:
        hits = [
            f
            for f in facts
            if (f.get("claim", {}).get("table_ref") or {}).get("row") == cell["row"]
            and (f.get("claim", {}).get("table_ref") or {}).get("column") == cell["columns"][0]
            and norm_number((f["claim"]["table_ref"].get("cell") or "")) == norm_number(cell["values"][0])
        ]
        matched = None
        for f in hits:
            unit_sources = {
                f["claim"].get("unit"),
                f["claim"].get("unit_raw"),
                f["claim"]["table_ref"].get("column"),
            }
            if cell["unit"] in unit_sources or (cell["unit"] == "%" and f["claim"].get("unit") == "%"):
                matched = f
                break
        cells.append(
            {
                "row": cell["row"],
                "column": cell["columns"][0],
                "expected": cell["values"][0],
                "unit": cell["unit"],
                "passed": matched is not None,
                "actual": [
                    {
                        "cell": f["claim"]["table_ref"].get("cell"),
                        "unit": f["claim"].get("unit"),
                        "unit_raw": f["claim"].get("unit_raw"),
                    }
                    for f in hits
                ],
            }
        )
    passed = sum(1 for c in cells if c["passed"])
    return {
        "frozen_run_id": CUSTOMER_RUN_ID,
        "doc_id": "2026-08-12_f0e67b73",
        "cells_passed": passed,
        "cells_total": len(cells),
        "cells": cells,
        "source_reparse": "not_run_holdout_protected",
        "note": "绑定口径：复现入口从冻结 run 重建（原文在 guards/i3.json forbidden_roots，开发期不读）",
    }


# ── 宏观冻结字段 0/3 保留 + 正文冻结 2 例（冻结 run 只读） ─────────────────


def macro_frozen() -> dict[str, object]:
    import psycopg

    with psycopg.connect(OLD_DSN, connect_timeout=5) as conn:
        payload = conn.execute(
            "select payload from corpus_evidence_runs where run_id = %s", (MACRO_RUN_ID,)
        ).fetchone()
    if payload is None:
        raise SystemExit("冻结宏观 run 不在库")
    facts = payload[0]["facts"]
    targets = [
        f
        for f in facts
        if f["claim"].get("subject") == "US"
        and f["claim"].get("metric") == "NFP"
        and f["claim"].get("period_end") == "2026-08-31"
        and f["claim"].get("qualifiers", {}).get("state") in {"actual", "consensus"}
    ]
    observed = sorted(
        (f["claim"]["qualifiers"]["state"], str(f["claim"].get("value_num"))) for f in targets
    )
    frozen_pair = [("actual", "16.2"), ("consensus", "5.6")]
    fields = {}
    for state, value in frozen_pair:
        hit = [f for f in targets if f["claim"]["qualifiers"]["state"] == state]
        fields[state] = {
            "present": bool(hit),
            "value": value,
            "usable_for": hit[0]["usable_for"] if hit else None,
            "calculate_ready": bool(hit) and "calculate" in hit[0]["usable_for"],
        }
    fields["previous"] = {
        "present": any(
            f["claim"].get("qualifiers", {}).get("state") == "previous" for f in facts
        ),
        "note": "r27：previous 移出分母（机器记录 2 targets）",
    }
    normalized = sum(
        1 for k in ("actual", "consensus") if fields[k]["calculate_ready"]
    )
    return {
        "frozen_run_id": MACRO_RUN_ID,
        "frozen_pair_matches": observed == frozen_pair,
        "machine_targets": len(targets),
        "normalized_count": normalized,
        "legacy_status_preserved": "0/3（单列，不伪装通过；previous 移出分母后机器口径 0/2）",
        "fields": fields,
        "known_reasons": "华泰『万』不可验证岗位单位；预期指标未统一；中银 basis『同比』≠冻结 YoY（semantic-repair-report L94）",
        "reextraction": "not_run_pending_budget",
    }


# ── 旧检索 golden 19 题（旧库只读，O6 留出排除） ──────────────────────────


def golden_19() -> dict[str, object]:
    from plugins.corpus.golden import GOLDEN_SET
    from plugins.corpus.service import CorpusService

    svc = CorpusService(dsn_url=OLD_DSN)
    chain = svc.read_chain()
    if chain != "legacy":
        raise SystemExit(f"旧库读链判定为 {chain!r}，预期 legacy（fail-closed）")
    questions = [q for q in GOLDEN_SET if q.qid != "O6"]
    if len(questions) != 19:
        raise SystemExit(f"golden 题数 {len(questions)} != 19")

    # O6 按 r27 冻结排除且不改 golden.py 字节：逐题复算 run_golden 同口径判定。
    results = []
    for question in questions:
        hits = svc.search(question.question, limit=5)
        matched, missing = [], []
        for matcher in question.expects:
            found = next(
                (
                    h
                    for h in hits
                    if matcher.title_contains in h.title
                    and (not matcher.doc_prefix or h.doc_id.startswith(matcher.doc_prefix))
                ),
                None,
            )
            (matched if found else missing).append(
                found.doc_id if found else f"{matcher.title_contains}/{matcher.doc_prefix}"
            )
        ok = not missing if question.require_all else bool(matched)
        results.append(
            {
                "qid": question.qid,
                "kind": question.kind,
                "hit": ok,
                "matched": matched,
                "missing": missing,
            }
        )
    passed = sum(1 for r in results if r["hit"])
    return {
        "read_chain": chain,
        "denominator": "19 题（O6 按 r27 冻结排除）",
        "passed": passed,
        "total": len(results),
        "recall": passed / len(results),
        "by_kind": {
            kind: {
                "passed": sum(1 for r in results if r["kind"] == kind and r["hit"]),
                "total": sum(1 for r in results if r["kind"] == kind),
            }
            for kind in sorted({r["kind"] for r in results})
        },
        "results": results,
        "note": "逐题通过口径（含 require_all）；不得删旧失败题，失败题逐题留痕",
    }


# ── 零模型约束门（审批/投影契约） ────────────────────────────────────────


def approval_contract_gate() -> dict[str, object]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(ING / "audits/20260918-i32-remediation/test_approval_contract.py"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    tail = (proc.stdout or "").strip().splitlines()[-6:]
    return {
        "exit_code": proc.returncode,
        "pytest_tail": tail,
        "passed": proc.returncode == 0,
        "asset": "audits/20260918-i32-remediation/test_approval_contract.py（离线合成，零模型零 PG）",
    }


def main() -> int:
    results: dict[str, object] = {}
    results["asset_hashes"] = check_hashes()
    forbidden = guard_forbidden()
    results["guard_forbidden_roots"] = forbidden

    results["financial_controlled_recalc_57"] = financial_recalc(forbidden)
    results["customer_table_12"] = customer_table_12()
    results["macro_legacy_and_prose_frozen"] = macro_frozen()
    results["legacy_retrieval_golden"] = golden_19()
    results["zero_model_approval_contract_gate"] = approval_contract_gate()

    fin = results["financial_controlled_recalc_57"]
    fin_ok = fin["financial_plus_formulas_passed"] == fin["target_dev_scope"]  # type: ignore[dict-item]
    neg_ok = fin["samples"]["image_only_source"].get("negative_control_passed") is True  # type: ignore[index]
    cust = results["customer_table_12"]
    cust_ok = cust["cells_passed"] == cust["cells_total"] == 12  # type: ignore[dict-item]
    macro = results["macro_legacy_and_prose_frozen"]
    macro_ok = macro["frozen_pair_matches"] and macro["normalized_count"] == 0  # type: ignore[dict-item]
    golden = results["legacy_retrieval_golden"]
    gate = results["zero_model_approval_contract_gate"]

    results["summary"] = {
        "financial_47_plus_formula_7": "PASS" if fin_ok else "FAIL",
        "negative_control": "PASS" if neg_ok else "FAIL",
        "guosen_maotai_holdout_10": "held_out_not_run_in_dev",
        "customer_table_12": "PASS（冻结 run 复验）" if cust_ok else "FAIL",
        "macro_legacy_0_of_3": "PRESERVED（失败基线保留）" if macro_ok else "CHANGED",
        "prose_numbers_frozen_2": "PASS（冻结 run 复验）" if macro_ok else "FAIL",
        "legacy_golden_19": f"{golden['passed']}/{golden['total']}",  # type: ignore[dict-item]
        "approval_contract_gate": "PASS" if gate["passed"] else "FAIL",  # type: ignore[dict-item]
        "not_run_items": {
            "prose_numbers_reextraction": "not_run_pending_budget（r27：复跑须另立预算授权）",
            "guosen_maotai_holdout_10_cells": "held_out_not_run_in_dev（I3-7 口径）",
            "customer_table_source_reparse": "not_run_holdout_protected",
            "real_answer_semantics_test": "not_run（未授权前不计作通过）",
        },
        "deviations": [
            "财务复验走 build_evidence_run 库级等价路径（原库零写入）：I2-7 后 canonical "
            "extract_claims 由 corpus_units 投影且 pilot 三份源不在 i0a2 批准开发集，"
            "冻结契约（verify_claims_entry.py 写原库 corpus_evidence_runs）不可原样执行；"
            "偏差如实登记，不宣称等同契约执行",
        ],
    }
    overall = fin_ok and neg_ok and cust_ok and macro_ok and gate["passed"]
    results["overall"] = {
        "financial_formula_negative_customer_macro_gate": overall,
        "golden_passed": golden["passed"],  # type: ignore[dict-item]
        "note": "golden 逐题结果单列；I3-5 不是最终版本放行",
    }

    out = AUDIT / "i35-results.json"
    if out.exists():
        raise SystemExit(f"write-once 冲突：{out} 已存在")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results["summary"], ensure_ascii=False, indent=1))
    print(f"results: {out}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
