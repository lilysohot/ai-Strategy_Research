"""P1 草稿：把批准投影材料化成评分器可读的 ``query-gold-with-targets``。

**只写审计目录、不落正式路径、不改冻结件**。

规则（最小改动，只增字段、不改既有字段）：
- ``answer_existence=answerable``（24 题）：新增 ``evidence_targets``（= 投影 ``approved_required``）
  与 ``supplementary_evidence_targets``（= 投影 ``supplementary``，**非必需**，不计入 EvidencePass）。
- ``answer_existence=no_answer``（6 题）：原样保留，不加 targets（评分器 ``_evidence_required`` 自动 False）。

每条例证再独立回验：``quote`` 与 source-gold 逐字一致、``source_id`` 与槽位一致、
``locator`` 与 ``_locator_tokens`` 一致、题内 ``target_id`` 唯一。最后用评分器自己的
``gold_from_records`` 干跑一遍（不构造观测），证明这份金标能被评分器原样吃下。

用法::

    env -u PYTHONPATH uv run python \\
      .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p1/materialize.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[2]  # ingestion-rebuild
ROOT = HERE.parents[5]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLD = BASE / "query-gold-frozen.jsonl"
PROJECTION = BASE / "i3-2/evidence-targets-approved.json"
SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
OUT_JSONL = HERE / "query-gold-with-targets.jsonl"
OUT_REPORT_JSON = HERE / "materialization-report.json"
OUT_REPORT_MD = HERE / "materialization-report.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_TARGET_KEYS = ("target_id", "quote", "locator", "source_id")


def to_target(target: Mapping[str, object]) -> dict[str, object]:
    """评分器只吃 4 个键；多出的 role/constraints/basis 保留作审计（会被 gold_from_records 忽略）。"""

    out: dict[str, object] = {}
    for key in _TARGET_KEYS:
        out[key] = target[key]
    for key in ("role", "constraints", "basis"):
        if key in target:
            out[key] = target[key]
    return out


def main() -> int:
    gold = load_jsonl(GOLD)
    projection = json.loads(PROJECTION.read_text(encoding="utf-8"))
    slots = load_jsonl(SOURCE_GOLD)
    applier = load_module(BASE / "i3s2_apply_decisions.py", "i3s2_applier_p1")
    slot_by_id = {str(slot["gold_id"]): slot for slot in slots}
    proj_by_id = {str(q["query_id"]): q for q in projection["questions"]}

    assert set(proj_by_id) == {str(record["query_id"]) for record in gold}, "投影与金标题号不一致"

    checks: list[dict] = []
    errors: list[str] = []
    out_records: list[dict] = []
    totals = {"required": 0, "supplementary": 0, "answerable": 0, "no_answer": 0}

    for record in gold:
        qid = str(record["query_id"])
        question = proj_by_id[qid]
        existence = str(record.get("answer_existence") or "")
        row: dict[str, object] = {"query_id": qid, "answer_existence": existence}

        if existence == "no_answer":
            totals["no_answer"] += 1
            row["required"] = 0
            row["supplementary"] = 0
            row["targets_added"] = False
            # 负例题原样保留（不加 evidence_targets；评分器 _evidence_required(no_answer)=False）
            if question.get("approved_required") or question.get("supplementary"):
                errors.append(f"{qid}: 负例题不应携带任何目标，投影却有 required/supplementary")
            out_records.append(record)
            checks.append(row)
            continue

        if existence != "answerable":
            errors.append(f"{qid}: answer_existence 非法 {existence!r}")
            out_records.append(record)
            checks.append(row)
            continue

        totals["answerable"] += 1
        required = [to_target(t) for t in question.get("approved_required") or []]
        supplementary = [to_target(t) for t in question.get("supplementary") or []]
        if not required:
            errors.append(f"{qid}: 有答案题但投影 required 为空")

        # 题内 target_id 唯一性 + 逐条回验 source-gold
        ids = [str(t["target_id"]) for t in required + supplementary]
        if len(ids) != len(set(ids)):
            errors.append(f"{qid}: 题内 target_id 重复")

        row["required"] = len(required)
        row["supplementary"] = len(supplementary)
        row["targets"] = []
        for t in required + supplementary:
            basis = t.get("basis") or {}
            slot = slot_by_id.get(str(basis.get("gold_id")))
            item = dict(applier.split_items(slot)).get(basis.get("item_index")) if slot else {}
            ok = True
            reasons = []
            if slot is None:
                ok, reasons = False, ["basis.gold_id 不在 source-gold"]
            else:
                if str(t.get("quote")) != str(item.get("quote")):
                    ok, reasons = False, reasons + ["quote 与 source-gold 不一致"]
                if str(t.get("source_id")) != str(slot.get("source_id")):
                    ok, reasons = False, reasons + ["source_id 与槽位不一致"]
                if list(t.get("locator") or []) != list(applier._locator_tokens(slot, item) or []):
                    ok, reasons = False, reasons + ["locator 与 _locator_tokens 不一致"]
            if not ok:
                errors.append(f"{qid}#{t['target_id']}: " + "; ".join(reasons))
            row["targets"].append(
                {
                    "target_id": t["target_id"],
                    "role": t.get("role"),
                    "ref": f"{basis.get('gold_id')}#{basis.get('item_index')}",
                    "ok": ok,
                    "reasons": reasons,
                }
            )
        totals["required"] += len(required)
        totals["supplementary"] += len(supplementary)
        row["targets_added"] = True

        new_record = dict(record)
        new_record["evidence_targets"] = required
        if supplementary:
            new_record["supplementary_evidence_targets"] = supplementary
        out_records.append(new_record)
        checks.append(row)

    # 评分器干跑：gold_from_records 直接吃下才算有效输入
    scorer_note = "skipped"
    scorer = {"questions": None, "evidence_targets_per_question": None}
    try:
        scoring = __import__("plugins.corpus.scoring", fromlist=["gold_from_records"])
        questions = scoring.gold_from_records(out_records)
        scorer = {
            "questions": len(questions),
            "evidence_targets_per_question": {
                str(q.query_id): len(q.evidence_targets) for q in questions
            },
        }
        scorer_note = "ok"
    except Exception as exc:  # noqa: BLE001
        scorer_note = f"failed: {type(exc).__name__}: {exc}"

    report = {
        "artifact": "i3-2-p1-query-gold-with-targets-DRAFT",
        "dryrun": True,
        "not_filed": "草稿：位于审计目录，未写正式路径、未改冻结件",
        "inputs": {
            "query_gold_sha256": digest(GOLD),
            "projection_sha256": digest(PROJECTION),
            "source_gold_sha256": digest(SOURCE_GOLD),
        },
        "totals": totals,
        "scorer_gold_from_records": {"status": scorer_note, **scorer},
        "errors": errors,
        "per_question": checks,
        "output_sha256": None,
    }
    OUT_JSONL.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in out_records) + "\n",
        encoding="utf-8",
    )
    report["output_sha256"] = digest(OUT_JSONL)
    OUT_REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = ["# P1 材料化逐题校验报告（草稿，未落正式）", ""]
    md.append(f"- 输入：`query-gold-frozen.jsonl` `{report['inputs']['query_gold_sha256'][:12]}…`"
              f"、投影 `{report['inputs']['projection_sha256'][:12]}…`"
              f"、`source-gold-frozen.jsonl` `{report['inputs']['source_gold_sha256'][:12]}…`")
    md.append(f"- 汇总：有答案 {totals['answerable']} 题 / 负例 {totals['no_answer']} 题；"
              f"必需 {totals['required']} 条 + 补充 {totals['supplementary']} 条")
    md.append(f"- 评分器 `gold_from_records` 干跑：**{scorer_note}**")
    if errors:
        md.append(f"- **错误 {len(errors)} 条**：")
        for error in errors:
            md.append(f"  - {error}")
    else:
        md.append("- **逐条回验全过**（quote/source_id/locator 与 source-gold 一致、题内 target_id 唯一）")
    md.append("")
    md.append("| query_id | 存在性 | 必需 | 补充 | 逐条回验 |")
    md.append("|---|---|---|---|---|")
    for row in checks:
        targets = row.get("targets")
        verdict = "—" if targets is None else ("全过" if all(t["ok"] for t in targets) else "有错")
        md.append(
            f"| {row['query_id']} | {row['answer_existence']} | {row['required']} | "
            f"{row['supplementary']} | {verdict} |"
        )
    md.append("")
    md.append("> 目标明细（target_id / role / source-gold 引用 / 是否一致）见 `materialization-report.json`。")
    OUT_REPORT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps(
        {"totals": totals, "errors": len(errors), "scorer_gold_from_records": scorer_note,
         "output": str(OUT_JSONL), "output_sha256": report["output_sha256"],
         "report_md": str(OUT_REPORT_MD), "report_json": str(OUT_REPORT_JSON)},
        ensure_ascii=False, indent=2,
    ))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
