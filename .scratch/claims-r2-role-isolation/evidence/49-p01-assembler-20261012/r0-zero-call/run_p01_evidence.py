"""P01 evidence: run the assembler against the real workbench and the gate-33 draft.

Zero model calls, read-only on every input. Writes only inside this evidence directory.

What it demonstrates:

1. The assembler's catalog is門 33 工作台 v2 (222 real candidates).
2. The gate-33 draft's 19 "accepted" records are **all rejected** — every one of them
   carries a gold-injected ``canonical_observed_fields`` (``build_adjudication_draft.py:98-100``).
3. Violation classes are tallied by probing each contract rule independently, so no
   violation is hidden behind another's fail-fast.
4. Valid adjudications currently assembled = 0 ⇒ gate 33 is 0 by construction, not by
   extraction quality. This is the measured form of §5.13.2's "link-end gap".

Usage:
    uv run python .scratch/.../49-p01-assembler-20261012/r0-zero-call/run_p01_evidence.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E49 = HERE.parent
CLAIMS = E49.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.adjudication_assembly import (  # noqa: E402
    ABSENT,
    ADJUDICATION_FIELDS,
    MATERIAL_ITEMS_CARRIERS,
    ROLE_REQUIRED_FIELDS,
    assemble_scoring_input,
    matching_view,
)
from plugins.corpus.structured_scoring import Role, ScoringInputError  # noqa: E402

EV = CLAIMS / "evidence"
CONTRACT = (
    EV / "47-scoring-contract-v41-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.1.json"
)
WORKBENCH = EV / "38-gate33-workbench-rebuild-20261012" / "r0-zero-call" / "workbench-v2.json"
DRAFT = EV / "33-items-quality-scoring-20261011" / "r0-zero-call" / "adjudications.draft.json"
DONOR_DRAFT_SCRIPT = (
    EV / "33-items-quality-scoring-20261011" / "r0-zero-call" / "build_adjudication_draft.py"
)


def sha256(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def probe_rules(record: dict[str, Any]) -> list[str]:
    """Independently probe each contract rule so violations are not masked by fail-fast."""
    violations: list[str] = []
    if not str(record.get("reviewer") or "").strip():
        violations.append("reviewer_missing")
    evidence = record.get("evidence")
    if not evidence:
        violations.append("evidence_missing")
    judgement = str(record.get("judgement") or "")
    if judgement not in {
        "matched",
        "correct_extra",
        "incorrect",
        "duplicate",
        "unresolved",
        "out_of_scope",
    }:
        violations.append("judgement_outside_contract_enum")
    declared = record.get("canonical_observed_fields") or {}
    for name in ROLE_REQUIRED_FIELDS[Role.MATERIAL_ITEMS]:
        value = declared.get(name)
        if value is None or str(value) == "":
            violations.append(f"required_field_blank::{name}")
    carrier = MATERIAL_ITEMS_CARRIERS["proposition"]
    native = str((record.get("original_candidate") or {}).get("text") or "")
    declared_prop = str(declared.get("proposition") or "")
    if carrier.is_deterministic and declared_prop and declared_prop != native:
        violations.append("proposition_rewritten_or_copied")
    for name in ("speech_role", "perspective"):
        native_value = str((record.get("original_candidate") or {}).get(name) or "")
        declared_value = str(declared.get(name) or "")
        if (
            declared_value
            and native_value
            and declared_value != native_value
            and matching_view(name, native_value) != declared_value
        ):
            violations.append(f"deterministic_field_declared_differently::{name}")
    for name in ("attribution", "speaker_ref", "source_stance"):
        if str(declared.get(name) or "") not in ("", ABSENT) and not (
            record.get("original_candidate") or {}
        ).get(name):
            violations.append(f"field_filled_from_outside_candidate::{name}")
    return violations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    workbench = json.loads(WORKBENCH.read_text(encoding="utf-8"))
    draft = json.loads(DRAFT.read_text(encoding="utf-8"))

    catalog = {str(row["candidate_id"]): row for row in workbench["candidates"]}
    draft_rows = draft["candidates"]
    by_judgement = Counter(str(row.get("judgement")) for row in draft_rows)
    accepted = [row for row in draft_rows if row.get("judgement") == "accepted"]

    # 1. Faithful run: hand the draft records to the assembler exactly as written.
    accepted_outcomes: list[dict[str, Any]] = []
    for row in accepted:
        try:
            assemble_scoring_input([row], catalog=catalog)
        except ScoringInputError as error:
            accepted_outcomes.append({"candidate_id": row["candidate_id"], "rejected": str(error)})
        else:
            accepted_outcomes.append({"candidate_id": row["candidate_id"], "rejected": None})

    rejected = [item for item in accepted_outcomes if item["rejected"]]
    accepted_count = len(accepted_outcomes) - len(rejected)

    # 2. Independent rule probing (no fail-fast masking).
    violation_tally: Counter[str] = Counter()
    per_record: list[dict[str, Any]] = []
    for row in accepted:
        found = probe_rules(row)
        violation_tally.update(found)
        per_record.append({"candidate_id": row["candidate_id"], "violations": found})

    # 3. What the assembler would produce if the adjudications were contract-valid.
    stage_tally = Counter(str(row.get("stage")) for row in draft_rows)
    required_missing = sorted(
        {name for row in draft_rows for name in ADJUDICATION_FIELDS if name not in row}
    )

    result = {
        "schema_version": "items-p01-assembler-evidence-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "model_requests": 0,
        "inputs": {
            str(CONTRACT.relative_to(REPO_ROOT)): sha256(CONTRACT),
            str(WORKBENCH.relative_to(REPO_ROOT)): sha256(WORKBENCH),
            str(DRAFT.relative_to(REPO_ROOT)): sha256(DRAFT),
            str(DONOR_DRAFT_SCRIPT.relative_to(REPO_ROOT)): sha256(DONOR_DRAFT_SCRIPT),
        },
        "contract_binding": {
            "schema_version": contract["schema_version"],
            "status": contract["status"],
            "signed_by": contract["signoff"]["signed_by"],
            "carriers_implemented": sorted(MATERIAL_ITEMS_CARRIERS),
            "role_required_fields": list(ROLE_REQUIRED_FIELDS[Role.MATERIAL_ITEMS]),
        },
        "catalog": {
            "source": str(WORKBENCH.relative_to(REPO_ROOT)),
            "candidates": len(catalog),
            "sources": sorted({str(row["source_id"]) for row in workbench["candidates"]}),
        },
        "draft_adjudications": {
            "total": len(draft_rows),
            "by_judgement": dict(by_judgement),
            "by_stage": dict(stage_tally),
            "contract_enum_violations": {
                "accepted": "adjudication_clause.candidate_judgements has no 'accepted'"
                " (record_states are a separate vocabulary and are not judgements)"
            }
            if "accepted" in by_judgement
            else {},
            "required_per_record_fields_absent_in_draft": required_missing,
        },
        "faithful_run": {
            "accepted_records_submitted": len(accepted),
            "assembled": accepted_count,
            "rejected": len(rejected),
            "first_violation_examples": rejected[:3],
            "verdict": "0 assembled: every gate-33 draft 'accepted' record violates contract v4.1",
        },
        "independent_rule_probe": {
            "violation_tally": dict(violation_tally.most_common()),
            "records_with_any_violation": sum(1 for row in per_record if row["violations"]),
            "records_with_no_violation": sum(1 for row in per_record if not row["violations"]),
            "per_record": per_record,
        },
        "blocking_conclusion": (
            "契约合法裁定数 = 0 ⇒ 装配器输出为空 ⇒ 门 33 的 0 分是**装配缺口**造成的，"
            "不是抽取质量问题。这以可执行形式证实了 §5.13.2『链路末端两处缺环』："
            "P01 装配器此前不存在，且现有草案裁定不是契约形态（含金标注入）。"
        ),
        "not_claimed": [
            "本产物不评价抽取质量，不产生任何门分数。",
            "本产物不修改 draft；draft 仍是其原样（其金标注入见 evidence/33 build_adjudication_draft.py:98-100）。",
            "『19 条被拒』不等于『19 条都真的不对』；它只说明其 canonical_observed_fields 非契约可接受形态。",
        ],
    }

    print(
        json.dumps(
            {k: result[k] for k in ("faithful_run", "independent_rule_probe")},
            ensure_ascii=False,
            indent=1,
        )[:2000]
    )
    if args.no_write:
        return

    (HERE / "p01-evidence.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "p01-evidence.md").write_text(render_md(result), encoding="utf-8")
    manifest = {
        "schema_version": "items-p01-manifest-1",
        "created_on": "2026-10-12",
        "inputs": result["inputs"],
        "outputs": {
            name: sha256(HERE / name)
            for name in (
                "p01-evidence.json",
                "p01-evidence.md",
                "run_p01_evidence.py",
                "preregistered-p01.json",
            )
            if (HERE / name).exists()
        },
        "in_place_edits": 0,
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_md(result: dict[str, Any]) -> str:
    lines = [
        "# P01 · 裁定→评分输入装配器 · 证据运行",
        "",
        "- 零模型调用；只读输入；`in_place_edits = 0`。",
        f"- 契约绑定：`{result['contract_binding']['schema_version']}`（`{result['contract_binding']['status']}`，"
        f"签认人 {result['contract_binding']['signed_by']}）",
        f"- 工作台目录：{result['catalog']['candidates']} 条候选 / {len(result['catalog']['sources'])} 个源",
        "",
        "## 一、忠实运行：门 33 草案的 19 条 `accepted` 全部被拒",
        "",
        f"- 提交：**{result['faithful_run']['accepted_records_submitted']}**　"
        f"装配成功：**{result['faithful_run']['assembled']}**　"
        f"拒绝：**{result['faithful_run']['rejected']}**",
        "",
        "| 候选 | 首个违约 |",
        "|---|---|",
    ]
    for item in result["faithful_run"]["first_violation_examples"]:
        lines.append(f"| `{item['candidate_id']}` | {item['rejected']} |")
    lines += [
        "",
        "## 二、独立规则探测（不被 fail-fast 掩盖）",
        "",
        "| 违约类 | 命中数 |",
        "|---|---|",
    ]
    for name, count in result["independent_rule_probe"]["violation_tally"].items():
        lines.append(f"| `{name}` | {count} |")
    lines += [
        "",
        f"- 有违约记录：**{result['independent_rule_probe']['records_with_any_violation']}**；"
        f"无违约记录：**{result['independent_rule_probe']['records_with_no_violation']}**",
        "",
        "## 三、草案与契约的形态差",
        "",
        f"- 草案 judgement 分布：`{result['draft_adjudications']['by_judgement']}`",
        f"- 草案 stage 分布：`{result['draft_adjudications']['by_stage']}`",
        f"- 草案缺失的 `required_per_record_fields`：{result['draft_adjudications']['required_per_record_fields_absent_in_draft']}",
        f"- 契约枚举冲突：{result['draft_adjudications']['contract_enum_violations']}",
        "",
        "## 四、结论",
        "",
        f"> {result['blocking_conclusion']}",
        "",
        "## 五、不宣称",
        "",
    ]
    lines += [f"- {item}" for item in result["not_claimed"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
