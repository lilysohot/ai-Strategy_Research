"""Issue-34 §7-9: same-type L3 audit for the `claims` and `material_relations` roles.

Zero call, read-only. Implements `preregistered-roles-l3.json` (write-once) and emits
roles-l3-audit.{json,md} plus MANIFEST.json.

Only `material_items` has measured production data in this workstream; `claims` has no
product at all and `material_relations` produced zero relations, so those roles are reported
at `code_level` / `absent_by_protocol` and are explicitly never written as measured.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/39-roles-l3-audit-20261012/r0-zero-call/roles_l3_audit.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E39 = HERE.parent
CLAIMS = E39.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import digest, read_json  # noqa: E402
from plugins.corpus.claims_detail import ClaimRecord  # noqa: E402

E10 = CLAIMS / "evidence"
E32 = CLAIMS / "evidence" / "32-items-v6-reasoning-refreeze-20261011"
E37_RESULT = (
    CLAIMS / "evidence" / "37-store-baseline-and-route-decision-20261012" / "r0-zero-call" / "store-baseline.json"
)
GOLD = E10 / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
CONTRACT = E10 / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
PREREG = HERE / "preregistered-roles-l3.json"
SOURCES = ("industrial-fulian-md", "optical-module-docx")

# claims: contract field -> (ClaimRecord attribute(s), carrier class, note)
CLAIMS_CODE_MAP: dict[str, tuple[str, str, str]] = {
    "subject": ("subject | subject_raw", "item_field", "直接同名"),
    "metric": ("metric | metric_raw", "item_field", "直接同名"),
    "period": ("period_raw | period_end | period_grain", "derived", "契约要 period，生产端按三种粒度拆开"),
    "unit": ("unit | unit_raw", "item_field", "直接同名"),
    "value": ("value_text | value_num", "item_field", "文本与数值两列"),
    "factuality": ("kind", "alias", "别名字段；取值域未核验，须实测后才能确认同轴"),
    "qualifier": ("qualifiers", "derived", "dict 结构，非单值"),
    "attribution": ("", "absent", "ClaimRecord 无承载字段"),
    "perspective": ("", "absent", "ClaimRecord 无承载字段"),
    "source_stance": ("", "absent", "ClaimRecord 无承载字段"),
    "estimate_status": ("", "absent", "ClaimRecord 无承载字段"),
}
RELATION_CODE_MAP = {
    "from_gold_record_id": ("", "structurally_unscoreable", "契约要求候选携带金标主键"),
    "to_gold_record_id": ("", "structurally_unscoreable", "契约要求候选携带金标主键"),
    "relation": ("understanding.relations[].type -> layer B text", "alias", "类型进 layer B 的 text 位"),
    "provenance": ("", "absent", "relation 投影未产出 provenance"),
}


def nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    prereg = read_json(PREREG)
    contract = read_json(CONTRACT)
    gold_payload = read_json(GOLD)
    e37 = read_json(E37_RESULT)
    required_by_role = contract["role_required_fields"]
    claim_fields = [f.name for f in dataclasses.fields(ClaimRecord)]

    # ---------------------------------------------------------------- gold side (measured)
    gold_by_role: dict[str, Any] = {}
    for role, fields in required_by_role.items():
        rows = [row for row in gold_payload["records"] if row["role"] == role]
        per_field = {}
        for field in fields:
            hits = sum(1 for row in rows if nonempty((row.get("semantic_fields") or {}).get(field)))
            per_field[field] = {
                "gold_nonempty": hits,
                "gold_total": len(rows),
                "distinct_values": len(
                    {
                        str((row.get("semantic_fields") or {}).get(field))
                        for row in rows
                        if nonempty((row.get("semantic_fields") or {}).get(field))
                    }
                ),
            }
        gold_by_role[role] = {"records": len(rows), "per_field": per_field}

    # ---------------------------------------------------------------- production side
    relations_measured: dict[str, Any] = {}
    for slug in SOURCES:
        for path in sorted(
            glob.glob(str(E32 / "live" / "treatment-store" / slug / "objects" / "sha256" / "*" / "*.json"))
        ):
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if not payload.get("understanding"):
                continue
            relations = payload["understanding"].get("relations") or []
            relations_measured[slug] = {
                "relation_count": len(relations),
                "object_sha256": "sha256:" + Path(path).name.removesuffix(".json"),
                "sample": relations[:1],
            }
            break
    total_relations = sum(item["relation_count"] for item in relations_measured.values())

    protocol_exclusion_quote = (
        "MATERIAL_ITEM_JSONL_PROMPT: 本阶段只抽 speakers 和 items，不输出 relations"
    )

    role_audit: dict[str, Any] = {}
    for role, fields in required_by_role.items():
        carrier: dict[str, Any] = {}
        for field in fields:
            if role == "material_items":
                classification = e37["ec_a1_field_carriers"]["classification"].get(field)
                source = "measured (evidence/37)"
                detail = e37["ec_a1_field_carriers"]["classification"].get(field)
            elif role == "claims":
                attr, klass, note = CLAIMS_CODE_MAP.get(field, ("", "unmapped", "未映射"))
                classification = klass
                source = "code_level (claims_detail.ClaimRecord)"
                detail = f"{attr or '—'}；{note}"
            else:
                attr, klass, note = RELATION_CODE_MAP.get(field, ("", "unmapped", "未映射"))
                classification = klass if total_relations == 0 else f"{klass}({attr})"
                source = "measured(0 relations) + code_level"
                detail = f"{attr or '—'}；{note}"
            carrier[field] = {
                "classification": classification,
                "evidence_source": source,
                "detail": detail,
                "gold_nonempty": gold_by_role[role]["per_field"][field]["gold_nonempty"],
            }
        absent = [
            field
            for field, blob in carrier.items()
            if blob["classification"] in ("absent", "structurally_unscoreable")
        ]
        role_audit[role] = {
            "gold_records": gold_by_role[role]["records"],
            "contract_required": fields,
            "carriers": carrier,
            "absent_or_unscoreable": absent,
        }

    # ---------------------------------------------------------------- verdicts (EC-B2/B3/B4)
    claims_absent = role_audit["claims"]["absent_or_unscoreable"]
    relations_unscoreable = [
        field
        for field, blob in role_audit["material_relations"]["carriers"].items()
        if blob["classification"].startswith("structurally_unscoreable")
    ]
    verdicts = {
        "material_items": {
            "verdict": "同型接缝（已实测确认）",
            "basis": "evidence/37：零载体必需字段 = source_stance；枚举轴口径相反",
            "level": "measured",
        },
        "claims": {
            "verdict": "疑似同型（同为『归属／来源态度／估计状态』族字段缺载体），但**未在数据上验证**",
            "basis": f"code_level：ClaimRecord 无 {claims_absent} 的承载字段；claims 运行产物在本范围不存在",
            "level": "code_level",
            "must_not_be_written_as": "同型接缝已确认",
        },
        "material_relations": {
            "verdict": "不同型：属协议范围外 + 契约结构性不可评分，不是字段错配",
            "basis": f"实测 relations 条数 = {total_relations}；协议明文排除（{protocol_exclusion_quote}）；"
            f"契约必需字段含金标主键 {relations_unscoreable}",
            "level": "measured + code_level",
        },
        "ec_b4_structurally_unscoreable": {
            "fields": relations_unscoreable,
            "consequence": "严格 identity 匹配要求候选 semantic_fields 逐字等于金标；"
            "要求候选携带金标主键，等于要求候选先知道答案 ⇒ 该角色在现评分器下恒为 0。",
        },
        "section_7_11_recommendation": {
            "choice": "每角色通用读路径机制（但先只对 items 落地）",
            "basis": "三角色的缺口同属『归属／来源态度／估计状态 + 口径归一化』这一族；"
            "写成 items-only 的条款将来必然在 claims 上重做一次；"
            "但 claims 缺产物、relations 属范围外，故本期只对 items 实现，机制留接口。",
        },
        "conflicts_with_issue34": [
            "§5.6『另两角色的同型接缝未验证』：现仍为未验证（claims code_level / relations 范围外），"
            "但可进一步确定 relations 不是字段错配而是协议范围外 + 契约含金标主键。",
        ],
    }

    result = {
        "schema_version": "items-roles-l3-audit-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "preregistration": {"path": PREREG.name, "sha256": digest(PREREG)},
        "scope_declaration": {
            "claims": "no production artifact in this workstream (items-only gate-32 protocol)",
            "material_relations": f"measured {total_relations} relations across both treatment sources",
            "protocol_exclusion_quote": protocol_exclusion_quote,
        },
        "gold_side": gold_by_role,
        "claim_record_code_fields": claim_fields,
        "relations_measured": relations_measured,
        "role_audit": role_audit,
        "verdicts": verdicts,
    }

    print(
        json.dumps(
            {
                "gold_records": {role: blob["records"] for role, blob in gold_by_role.items()},
                "relations_total": total_relations,
                "items_absent": role_audit["material_items"]["absent_or_unscoreable"],
                "claims_absent_code_level": claims_absent,
                "relations_unscoreable": relations_unscoreable,
                "recommendation": verdicts["section_7_11_recommendation"]["choice"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return

    (HERE / "roles-l3-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "roles-l3-audit.md").write_text(render_md(result), encoding="utf-8")
    manifest = {
        "schema_version": "items-roles-l3-audit-manifest-1",
        "created_on": "2026-10-12",
        "inputs": {
            str(PREREG.relative_to(REPO_ROOT)): digest(PREREG),
            str(GOLD.relative_to(REPO_ROOT)): digest(GOLD),
            str(CONTRACT.relative_to(REPO_ROOT)): digest(CONTRACT),
            str(E37_RESULT.relative_to(REPO_ROOT)): digest(E37_RESULT),
            "plugins/corpus/claims_detail.py": digest(REPO_ROOT / "plugins/corpus/claims_detail.py"),
            "plugins/corpus/structured/store.py": digest(
                REPO_ROOT / "plugins/corpus/structured/store.py"
            ),
            **{
                f"store_object::{slug}": relations_measured[slug]["object_sha256"]
                for slug in relations_measured
            },
        },
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "preregistered-roles-l3.json",
                "roles-l3-audit.json",
                "roles-l3-audit.md",
                "roles_l3_audit.py",
            )
        },
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_md(result: dict[str, Any]) -> str:
    lines = [
        "# claims / material_relations 同型 L3 审计（§7-9）",
        "",
        f"- 预注册：`{result['preregistration']['path']}` `{result['preregistration']['sha256']}`",
        f"- 范围声明：claims = {result['scope_declaration']['claims']}；"
        f"relations = {result['scope_declaration']['material_relations']}",
        "",
        "## 金标侧（实测）",
        "",
        "| 角色 | 金标记录数 |",
        "|---|---|",
    ]
    for role, blob in result["gold_side"].items():
        lines.append(f"| `{role}` | {blob['records']} |")
    for role, blob in result["role_audit"].items():
        lines += [
            "",
            f"## `{role}`：契约必需字段 × 载体",
            "",
            "| 契约字段 | gold 非空 | 生产端载体 | 依据 |",
            "|---|---|---|---|",
        ]
        for field, carrier in blob["carriers"].items():
            lines.append(
                "| `{0}` | {1}/{2} | {3} | {4} |".format(
                    field,
                    carrier["gold_nonempty"],
                    blob["gold_records"],
                    carrier["classification"],
                    carrier["evidence_source"],
                )
            )
        lines.append("")
        lines.append(f"- 无载体/不可评分字段：{blob['absent_or_unscoreable'] or '（无）'}")
    lines += ["", "## 判定", ""]
    for role in ("material_items", "claims", "material_relations"):
        blob = result["verdicts"][role]
        lines.append(f"- **{role}**（{blob['level']}）：{blob['verdict']}")
        lines.append(f"  - 依据：{blob['basis']}")
    lines += [
        "",
        "### EC-B4 结构性不可评分",
        "",
        f"- 字段：{result['verdicts']['ec_b4_structurally_unscoreable']['fields']}",
        f"- 后果：{result['verdicts']['ec_b4_structurally_unscoreable']['consequence']}",
        "",
        "### §7-11 建议（EC-B5）",
        "",
        f"- 结论：**{result['verdicts']['section_7_11_recommendation']['choice']}**",
        f"- 依据：{result['verdicts']['section_7_11_recommendation']['basis']}",
        "",
        "## 与 issue-34 的对照",
        "",
    ]
    lines += [f"- {item}" for item in result["verdicts"]["conflicts_with_issue34"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
