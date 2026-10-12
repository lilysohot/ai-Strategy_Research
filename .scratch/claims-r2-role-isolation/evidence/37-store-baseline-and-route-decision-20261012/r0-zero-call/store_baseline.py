"""Store-layer field baseline for the items seam, and the route-a/route-b decision evidence.

Zero call, read-only. Implements `preregistered-store-baseline.json` (write-once, written
before this script runs) and emits store-baseline.{json,md}, route-decision.json and
MANIFEST.json.

The candidate baseline is the production store product
(`32-…/live/treatment-store/<slug>/objects/…`), NOT the gate-33 workbench projection.

Usage:
    uv run python .scratch/claims-r2-role-isolation/evidence/37-store-baseline-and-route-decision-20261012/r0-zero-call/store_baseline.py
    ... --no-write
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E37 = HERE.parent
CLAIMS = E37.parent.parent
REPO_ROOT = HERE.parents[4]
E36_R0 = CLAIMS / "evidence" / "36-l9-redo-and-baseline-20261011" / "r0-zero-call"
for path in (str(REPO_ROOT), str(E36_R0)):
    if path not in sys.path:
        sys.path.insert(0, path)

from l9_redo import covering_slots, digest, norm, read_json  # noqa: E402
from plugins.corpus.material_semantics import MaterialRun  # noqa: E402
from plugins.corpus.structured.ledger import BatchPlan  # noqa: E402
from plugins.corpus.structured.store import _material_records  # noqa: E402

E10 = CLAIMS / "evidence"
E32_LIVE = CLAIMS / "evidence" / "32-items-v6-reasoning-refreeze-20261011" / "live"
STORE = E32_LIVE / "treatment-store"
WORKBENCH = CLAIMS / "evidence" / "33-items-quality-scoring-20261011" / "r0-zero-call" / "workbench.json"
GOLD = E10 / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"
CONTRACT = E10 / "10-quality-gold-expansion-20261008-r2" / "scoring-contract.json"
PREREG = HERE / "preregistered-store-baseline.json"
SELF = Path(__file__).resolve()

SEM5 = ("semantic_type", "statement_role", "speech_role", "perspective", "polarity")
NORMALIZATION = {
    "perspective": {"source_explicit": "unknown"},
    "speech_role": {"question": "statement", "answer": "statement", "unknown": "statement"},
}
DEVELOPMENT_SLUG = "optical-module-docx"
HELD_OUT_SLUG = "industrial-fulian-md"


def normalize_view(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    for field, table in NORMALIZATION.items():
        value = out.get(field)
        if isinstance(value, str) and value in table:
            out[field] = table[value]
    return out


def load_store_runs() -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for path in sorted(glob.glob(str(STORE / "*" / "objects" / "sha256" / "*" / "*.json"))):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not payload.get("understanding"):
            continue
        slug = path.split("treatment-store/")[1].split("/")[0]
        runs[slug] = {"path": path, "payload": payload}
    return runs


def slot_index(items: list[dict[str, Any]], slots: list[dict[str, Any]]) -> tuple[list[dict], dict]:
    """Attach candidate_slot_id by evidence-span containment; report unassignable."""
    by_slot: dict[str, list[dict[str, Any]]] = {}
    enriched: list[dict[str, Any]] = []
    unassignable: list[str] = []
    for item in items:
        evidence = (item.get("evidence") or [{}])[0]
        packet_id, start, end = evidence.get("packet_id"), evidence.get("start"), evidence.get("end")
        slot_id = None
        for slot in slots:
            if (
                slot.get("packet_id") == packet_id
                and start is not None
                and end is not None
                and slot.get("start") <= start
                and end <= slot.get("end")
            ):
                slot_id = slot["candidate_slot_id"]
                break
        if slot_id is None:
            unassignable.append(item["item_id"])
            continue
        entry = dict(item, candidate_slot_id=slot_id)
        enriched.append(entry)
        by_slot.setdefault(slot_id, []).append(entry)
    return enriched, {"by_slot": by_slot, "unassignable": unassignable}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    prereg = read_json(PREREG)
    contract = read_json(CONTRACT)
    gold_payload = read_json(GOLD)
    gold_items = [row for row in gold_payload["records"] if row["role"] == "material_items"]
    gold_by_id = {row["record_id"]: row for row in gold_items}
    required = list(contract["role_required_fields"]["material_items"])
    workbench = read_json(WORKBENCH)

    runs = load_store_runs()
    store: dict[str, Any] = {}
    for slug, blob in runs.items():
        understanding = blob["payload"]["understanding"]
        items, slots = understanding["items"], blob["payload"]["candidate_slots"]
        enriched, index = slot_index(items, slots)
        store[slug] = {
            "run_id": blob["payload"].get("run_id"),
            "extractor_version": blob["payload"].get("extractor_version"),
            "contract_version": understanding.get("contract_version"),
            "object_sha256": "sha256:" + blob["path"].split("/")[-1].removesuffix(".json"),
            "items": enriched,
            "slots": slots,
            "by_slot": index["by_slot"],
            "speakers": understanding.get("speakers") or [],
            "unassignable": index["unassignable"],
        }

    # ---------------------------------------------------------------- coverage (same logic as round 36)
    coverage = {
        slug: covering_slots(
            slug,
            gold_items,
            [
                {"candidate_id": item["item_id"], "candidate_slot_id": item["candidate_slot_id"]}
                for item in store[slug]["items"]
            ],
        )
        for slug in store
    }
    candidates_in_slots = {
        slug: {slot_id: items for slot_id, items in store[slug]["by_slot"].items()}
        for slug in store
    }
    gold_slug: dict[str, str] = {}

    def candidates_for(record_id: str) -> list[dict[str, Any]]:
        for slug, blob in coverage.items():
            info = blob["per_gold"].get(record_id)
            if info is None:
                continue
            return [
                item
                for slot_id in info["covering_slot_ids"]
                for item in candidates_in_slots[slug].get(slot_id, [])
            ]
        return []

    for row in gold_items:
        for slug, blob in coverage.items():
            if row["record_id"] in blob["per_gold"]:
                gold_slug[row["record_id"]] = slug

    # ---------------------------------------------------------------- EC-A1 field carriers
    item_fields_present: dict[str, int] = {}
    for slug in store:
        for item in store[slug]["items"]:
            for key, value in item.items():
                if key in ("item_id", "evidence", "candidate_slot_id"):
                    continue
                if isinstance(value, str) and value.strip():
                    item_fields_present[key] = item_fields_present.get(key, 0) + 1
    all_item_keys = sorted(
        {
            key
            for slug in store
            for item in store[slug]["items"]
            for key in item
            if key not in ("item_id", "evidence", "candidate_slot_id")
        }
    )
    # layer B: the store's own structured projection (`structured/store.py::_material_records`)
    layer_b: dict[str, Any] = {}
    for slug in store:
        run = MaterialRun.model_validate(runs[slug]["payload"])
        plan = BatchPlan.model_validate_json(
            (
                CLAIMS
                / "evidence"
                / "32-items-v6-reasoning-refreeze-20261011"
                / "r0-zero-call"
                / f"plan-treatment-{slug}.json"
            ).read_text(encoding="utf-8")
        )
        records, _ = _material_records(run, plan.snapshot)
        fields = ("attribution", "condition", "factuality", "polarity", "value")
        agreement: dict[str, int] = {}
        for field, gold_field in (
            ("attribution", "attribution"),
            ("condition", "condition"),
            ("factuality", "semantic_type"),
        ):
            hits = 0
            for row in gold_items:
                gold_value = (row.get("semantic_fields") or {}).get(gold_field)
                info = coverage[slug]["per_gold"].get(row["record_id"])
                if not info or not gold_value:
                    continue
                if any(
                    getattr(records.get(item_id), field, None) == gold_value
                    for item_id in info["candidate_ids"]
                    if records.get(item_id) is not None
                ):
                    hits += 1
            agreement[gold_field] = hits
        layer_b[slug] = {
            "records": len(records),
            "value_distributions": {
                field: dict(Counter(getattr(rec, field) for rec in records.values()))
                for field in fields
            },
            "gold_raw_agreement": agreement,
        }

    carrier_class: dict[str, str] = {}
    for field in required + ["condition"]:
        if field == "proposition":
            carrier_class[field] = "text_carried"
        elif field in all_item_keys and item_fields_present.get(field, 0) > 0:
            carrier_class[field] = "item_field"
        elif field in ("attribution", "condition"):
            carrier_class[field] = "item_field_layer_b_coarse"
        else:
            carrier_class[field] = "absent"
    absent_required = [
        field
        for field in required
        if carrier_class.get(field) == "absent"
    ]
    coarse_required = [
        field
        for field in required
        if carrier_class.get(field) == "item_field_layer_b_coarse"
    ]

    # ---------------------------------------------------------------- EC-A2 per-field agreement
    field_agreement: dict[str, Any] = {}
    available_records = sum(
        1 for row in gold_items if candidates_for(row["record_id"])
    )
    for field in SEM5:
        raw_hits: list[str] = []
        norm_hits: list[str] = []
        for row in gold_items:
            record_id = row["record_id"]
            gold_value = (row.get("semantic_fields") or {}).get(field)
            cands = candidates_for(record_id)
            if not cands:
                continue
            raw = any(item.get(field) == gold_value for item in cands)
            gold_norm = NORMALIZATION.get(field, {}).get(gold_value, gold_value)
            normed = any(normalize_view(item).get(field) == gold_norm for item in cands)
            if raw:
                raw_hits.append(record_id)
            if normed:
                norm_hits.append(record_id)
        field_agreement[field] = {
            "gold_distribution": dict(
                Counter((row.get("semantic_fields") or {}).get(field) for row in gold_items)
            ),
            "store_distribution": dict(
                Counter(
                    item.get(field)
                    for slug in store
                    for item in store[slug]["items"]
                )
            ),
            "records_with_raw_agreement": len(raw_hits),
            "records_with_normalized_agreement": len(norm_hits),
            "denominator_all_gold": 48,
            "denominator_records_with_candidates": available_records,
            "normalized_agreement_rate_of_all_gold": round(len(norm_hits) / 48, 4),
            "normalized_agreement_rate_of_available": None
            if not available_records
            else round(len(norm_hits) / available_records, 4),
            "caliber_gap_removed_by_normalization": len(norm_hits) - len(raw_hits),
            "extraction_gap_remaining": 48 - len(norm_hits),
            "below_half_ambiguous_denominator": {
                "of_all_gold": len(norm_hits) < 24,
                "of_available": len(norm_hits) < available_records / 2,
            },
        }

    # ---------------------------------------------------------------- EC-A3 tuple alignment
    def tuple_alignment(fields: tuple[str, ...]) -> dict[str, Any]:
        hits: list[str] = []
        by_source: dict[str, list[str]] = {slug: [] for slug in coverage}
        for row in gold_items:
            record_id = row["record_id"]
            cands = candidates_for(record_id)
            if not cands:
                continue
            gold_view = normalize_view(row.get("semantic_fields") or {})
            if any(
                all(normalize_view(item).get(field) == gold_view.get(field) for field in fields)
                for item in cands
            ):
                hits.append(record_id)
                by_source[gold_slug.get(record_id, "?")].append(record_id)
        return {
            "fields": list(fields),
            "records": len(hits),
            "record_ids": sorted(hits),
            "by_source": {slug: len(ids) for slug, ids in by_source.items()},
        }

    tuple_results = {
        "5tuple": tuple_alignment(SEM5),
        "4tuple_no_polarity": tuple_alignment(
            ("semantic_type", "statement_role", "speech_role", "perspective")
        ),
        "3tuple_no_speech_role": tuple_alignment(
            ("semantic_type", "statement_role", "perspective")
        ),
        "2tuple_core": tuple_alignment(("semantic_type", "statement_role")),
    }

    # ---------------------------------------------------------------- EC-A4 speaker granularity
    gold_speaker = Counter((row.get("semantic_fields") or {}).get("speaker_ref") for row in gold_items)
    gold_attribution = Counter((row.get("semantic_fields") or {}).get("attribution") for row in gold_items)
    store_speakers = {
        slug: dict(Counter(item.get("speaker_ref") for item in store[slug]["items"])) for slug in store
    }
    redundant = all(
        sorted(
            rid
            for rid, row in gold_by_id.items()
            if (row["semantic_fields"] or {}).get("attribution") == label
        )
        == sorted(
            rid
            for rid, row in gold_by_id.items()
            if (row["semantic_fields"] or {}).get("speaker_ref") == ref
        )
        for label, ref in (
            ("报告作者", "md_author"),
            ("未署名讲者", "doc_narrator"),
            ("材料转述的德科立", "doc_dekeli"),
            ("材料转述的公司", "doc_quoted_company"),
            ("讲者转述的未明确来源", "doc_quoted_unknown"),
        )
    )
    speaker_granularity = {
        "gold_distinct_attribution": len(gold_attribution),
        "gold_distinct_speaker_ref": len(gold_speaker),
        "store_distinct_speaker_ref": {slug: len(v) for slug, v in store_speakers.items()},
        "store_speakers_detail": store_speakers,
        "store_speaker_records": {slug: store[slug]["speakers"] for slug in store},
        "attribution_speaker_ref_are_one_to_one_in_gold": redundant,
        "derivable": False,
        "reason": "store 侧只有 document_voice/quoted_source 两个说话人且 display_name 为空，"
        "gold 侧需 5 类区分（其中 attribution 与 speaker_ref 在 gold 内 1:1 冗余）⇒ 粒度不足，不可派生。",
    }

    # ---------------------------------------------------------------- EC-A5 gate-33 projection defect
    wb_fields = sorted({key for cand in workbench["candidates"] for key in cand})
    store_fields = sorted(all_item_keys + ["candidate_slot_id", "evidence_quote", "evidence_locator"])
    dropped = sorted(set(all_item_keys) - {key for cand in workbench["candidates"] for key in cand})
    projection_defect = {
        "workbench_candidate_fields": wb_fields,
        "store_item_fields": sorted(all_item_keys),
        "store_fields_missing_in_workbench": dropped,
        "affected_items": {
            key: item_fields_present.get(key, 0) for key in dropped
        },
        "affects_gate33_stage2": bool(dropped),
        "note": "门 33 Stage 2 的裁定者看不到 store 层已存在的字段 ⇒ 即使人工裁定也无法读取该轴；"
        "报分前须先重建工作台（零调用）。",
    }

    # ---------------------------------------------------------------- route decision
    ra = tuple_results["5tuple"]["records"]
    ra_held = tuple_results["5tuple"]["by_source"].get(HELD_OUT_SLUG, 0)
    low_agreement = [
        field
        for field, blob in field_agreement.items()
        if blob["below_half_ambiguous_denominator"]["of_all_gold"]
    ]
    low_agreement_available = [
        field
        for field, blob in field_agreement.items()
        if blob["below_half_ambiguous_denominator"]["of_available"]
    ]
    if ra >= 1 and set(absent_required) <= {"attribution", "source_stance"}:
        branch = "EC-A6a"
        verdict = (
            f"路线 a 存在可执行路径（absent={absent_required}，归一化后 5 元组对齐 {ra}/48）；"
            "route b 不必为『字段缺失』而行。"
        )
    else:
        branch = "EC-A6b"
        verdict = (
            f"归一化后 5 元组对齐仍为 {ra}/48（held-out {ra_held}）⇒ 路线 a 无法以『字段对齐』闭合；"
            "须在『缩到 semantic_type+statement_role 并接受大量人工裁定』与『改协议口径并重抽』之间裁定。"
        )
    route = {
        "schema_version": "items-route-decision-1",
        "created_on": "2026-10-12",
        "branch": branch,
        "verdict": verdict,
        "inputs": {
            "absent_required_fields": absent_required,
            "coarse_carrier_required_fields": coarse_required,
            "ra_5tuple": ra,
            "ra_5tuple_held_out": ra_held,
            "ra_2tuple_core": tuple_results["2tuple_core"]["records"],
            "fields_below_50pct_after_normalization": low_agreement,
            "fields_below_50pct_after_normalization_of_available": low_agreement_available,
            "pre_registration_ambiguity": (
                "EC-A6c 未写明 <50% 的分母（全体 48 还是覆盖槽位内有候选的 39）。"
                "按全体触发项为 {0}，按可判分口径触发项为 {1}；两种口径都已列出，裁定前不得只取其一。".format(
                    low_agreement or "（无）", low_agreement_available or "（无）"
                )
            ),
            "corpus_absent_records": sum(
                1 for slug in coverage for info in coverage[slug]["per_gold"].values()
                if not info["candidate_ids"]
            ),
        },
        "cost_comparison": {
            "route_a": "零模型调用：重建工作台（修投影，补 speaker_ref）+ 复用 store 自身已实现的 condition/attribution 派生"
            "（`structured/store.py:487-499`）+ 定枚举口径归一化条款 + 定 source_stance 条款；"
            f"自动对齐记录数 = {ra}/48（见 ra_5tuple），其余靠人工裁定。"
            f"零载体必需字段 = {absent_required}；载体存在但口径过粗 = {coarse_required}。",
            "route_b": "改协议/口径后重抽：作废门 32 冻结 + 新门 + 真实调用（222 条候选重生）+ 重冻结；"
            f"另需覆盖 {sum(1 for slug in coverage for info in coverage[slug]['per_gold'].values() if not info['candidate_ids'])} "
            "条覆盖槽位内无候选的记录。其唯一不可替代之处是把口径写进协议而非事后映射。",
        },
        "ec_a4": speaker_granularity["reason"],
        "ec_a5": projection_defect["note"],
    }

    conflicts_with_r2 = [
        "EC-1（『4 个字段在候选上零载体』）须**收回重写**：零载体必需字段实测为 "
        f"{absent_required or '（无）'}；proposition 由 text 承载、speaker_ref 在 layer A 有载体、"
        "attribution 在 layer B 有载体（口径过粗）。",
        "§5.2/§3 L3 的候选字段数：layer A 语义字段 11（含 speaker_ref），门 33 投影 10，layer B 为 7。",
        "§5.8 的『route a 无法产出契约形态记录』：该结论只在门 33 投影口径下成立。",
    ]

    result = {
        "schema_version": "items-store-baseline-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "preregistration": {"path": PREREG.name, "sha256": digest(PREREG)},
        "store_runs": {
            slug: {
                "run_id": store[slug]["run_id"],
                "extractor_version": store[slug]["extractor_version"],
                "contract_version": store[slug]["contract_version"],
                "object_sha256": store[slug]["object_sha256"],
                "items": len(store[slug]["items"]),
                "slots": len(store[slug]["slots"]),
                "speakers": len(store[slug]["speakers"]),
                "unassignable_items": store[slug]["unassignable"],
            }
            for slug in store
        },
        "ec_a1_field_carriers": {
            "contract_required": required,
            "store_item_keys": sorted(all_item_keys),
            "classification": carrier_class,
            "absent_required_fields": absent_required,
            "coarse_carrier_required_fields": coarse_required,
            "layer_b_note": "layer B = `plugins/corpus/structured/store.py::_material_records`（store 自身的结构化投影），"
            "由 layer A + snapshot 确定性派生，实测调用真实函数得到；attribution 值域仅 document_voice/None，"
            "condition 值域为 conditional/unconditional，与金标口径不同。",
        },
        "ec_a1_layer_b": layer_b,
        "ec_a2_field_agreement": field_agreement,
        "ec_a3_tuple_alignment": tuple_results,
        "ec_a4_speaker_granularity": speaker_granularity,
        "ec_a5_projection_defect": projection_defect,
        "conflicts_with_r2": conflicts_with_r2,
    }

    print(
        json.dumps(
            {
                "absent_required_fields": absent_required,
                "ra_5tuple": tuple_results["5tuple"]["records"],
                "ra_held_out": ra_held,
                "ra_2tuple_core": tuple_results["2tuple_core"]["records"],
                "per_field_normalized_agreement": {
                    field: blob["records_with_normalized_agreement"]
                    for field, blob in field_agreement.items()
                },
                "store_missing_in_workbench": dropped,
                "branch": branch,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.no_write:
        return

    (HERE / "store-baseline.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "route-decision.json").write_text(
        json.dumps(route, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "store-baseline.md").write_text(render_md(result, route), encoding="utf-8")
    manifest = {
        "schema_version": "items-store-baseline-manifest-1",
        "created_on": "2026-10-12",
        "inputs": {
            str(PREREG.relative_to(REPO_ROOT)): digest(PREREG),
            str(WORKBENCH.relative_to(REPO_ROOT)): digest(WORKBENCH),
            str(GOLD.relative_to(REPO_ROOT)): digest(GOLD),
            str(CONTRACT.relative_to(REPO_ROOT)): digest(CONTRACT),
            str((E36_R0 / "l9_redo.py").relative_to(REPO_ROOT)): digest(E36_R0 / "l9_redo.py"),
            "plugins/corpus/structured/store.py": digest(
                REPO_ROOT / "plugins/corpus/structured/store.py"
            ),
            "plugins/corpus/material_semantics.py": digest(
                REPO_ROOT / "plugins/corpus/material_semantics.py"
            ),
            **{f"store_object::{slug}": store[slug]["object_sha256"] for slug in store},
        },
        "outputs": {
            name: digest(HERE / name)
            for name in (
                "preregistered-store-baseline.json",
                "store-baseline.json",
                "route-decision.json",
                "store-baseline.md",
                "store_baseline.py",
            )
        },
        "self": str(SELF),
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_md(result: dict[str, Any], route: dict[str, Any]) -> str:
    lines = [
        "# store 层字段基线（路线 a/b 裁定依据）",
        "",
        f"- 预注册：`{result['preregistration']['path']}` `{result['preregistration']['sha256']}`",
        "- 候选基线 = 生产 store 产物（**不是**门 33 工作台投影）",
        "",
        "## store 运行对象",
        "",
        "| 源 | extractor | items | slots | speakers | 未可归属 | 对象哈希 |",
        "|---|---|---|---|---|---|---|",
    ]
    for slug, blob in result["store_runs"].items():
        lines.append(
            "| {0} | `{1}` | {2} | {3} | {4} | {5} | `{6}` |".format(
                slug,
                blob["extractor_version"],
                blob["items"],
                blob["slots"],
                blob["speakers"],
                len(blob["unassignable_items"]),
                blob["object_sha256"][7:19] + "…",
            )
        )
    carriers = result["ec_a1_field_carriers"]
    lines += ["", "## EC-A1 契约字段在 store 层的载体", "", "| 契约字段 | 载体类别 |", "|---|---|"]
    for field in carriers["contract_required"] + ["condition"]:
        lines.append(f"| `{field}` | {carriers['classification'][field]} |")
    lines += [
        "",
        f"**零载体必需字段：{carriers['absent_required_fields'] or '（无）'}**；"
        f"载体存在但口径过粗：{carriers['coarse_carrier_required_fields'] or '（无）'}",
        "",
        f"> {carriers['layer_b_note']}",
        "",
        "### layer B（store 自身结构化投影，实测调用）",
        "",
        "| 源 | 记录数 | attribution | condition | factuality | polarity | gold raw 一致 |",
        "|---|---|---|---|---|---|---|",
    ]
    for slug, blob in result["ec_a1_layer_b"].items():
        dist = blob["value_distributions"]
        lines.append(
            "| {0} | {1} | {2} | {3} | {4} | {5} | {6} |".format(
                slug,
                blob["records"],
                json.dumps(dist["attribution"], ensure_ascii=False),
                json.dumps(dist["condition"], ensure_ascii=False),
                json.dumps(dist["factuality"], ensure_ascii=False),
                json.dumps(dist["polarity"], ensure_ascii=False),
                json.dumps(blob["gold_raw_agreement"], ensure_ascii=False),
            )
        )
    lines += [
        "",
        "## EC-A2 逐字段一致性（覆盖槽位内，按金标记录）",
        "",
        "| 字段 | raw 一致 | 归一化后一致 | 口径差可消 | 抽取差剩余 |",
        "|---|---|---|---|---|",
    ]
    for field, blob in result["ec_a2_field_agreement"].items():
        lines.append(
            "| `{0}` | {1}/48 | {2}/48 | +{3} | {4} |".format(
                field,
                blob["records_with_raw_agreement"],
                blob["records_with_normalized_agreement"],
                blob["caliber_gap_removed_by_normalization"],
                blob["extraction_gap_remaining"],
            )
        )
    lines += [
        "",
        "### 金标 vs store 分布",
        "",
    ]
    for field, blob in result["ec_a2_field_agreement"].items():
        lines.append(f"- `{field}`")
        lines.append(f"  - gold：{json.dumps(blob['gold_distribution'], ensure_ascii=False)}")
        lines.append(f"  - store：{json.dumps(blob['store_distribution'], ensure_ascii=False)}")
    tup = result["ec_a3_tuple_alignment"]
    lines += [
        "",
        "## EC-A3 归一化后元组对齐（覆盖槽位内）",
        "",
        "| 元组 | 对齐记录数 | md（held-out） | docx（dev） |",
        "|---|---|---|---|",
    ]
    for name, blob in tup.items():
        lines.append(
            "| {0} | {1}/48 | {2} | {3} |".format(
                name,
                blob["records"],
                blob.get("by_source", {}).get("industrial-fulian-md", 0),
                blob.get("by_source", {}).get("optical-module-docx", 0),
            )
        )
    lines += [
        "",
        f"- 5 元组对齐记录：{tup['5tuple']['record_ids']}",
        "",
        "## EC-A4 说话人粒度",
        "",
        f"- gold 不同 attribution 数：{result['ec_a4_speaker_granularity']['gold_distinct_attribution']}；"
        f"gold 不同 speaker_ref 数：{result['ec_a4_speaker_granularity']['gold_distinct_speaker_ref']}",
        f"- store 不同 speaker_ref 数：{result['ec_a4_speaker_granularity']['store_distinct_speaker_ref']}",
        f"- store speakers 明细：{json.dumps(result['ec_a4_speaker_granularity']['store_speaker_records'], ensure_ascii=False)}",
        f"- gold 内 attribution 与 speaker_ref 是否 1:1 冗余：{result['ec_a4_speaker_granularity']['attribution_speaker_ref_are_one_to_one_in_gold']}",
        f"- 可派生：**{result['ec_a4_speaker_granularity']['derivable']}** — {result['ec_a4_speaker_granularity']['reason']}",
        "",
        "## EC-A5 门 33 投影缺陷",
        "",
        f"- workbench 相对 store 丢失的字段：{result['ec_a5_projection_defect']['store_fields_missing_in_workbench']}",
        f"- 受影响 item 数：{json.dumps(result['ec_a5_projection_defect']['affected_items'], ensure_ascii=False)}",
        f"- 影响 Stage 2 可执行性：**{result['ec_a5_projection_defect']['affects_gate33_stage2']}**",
        "",
        "## 路线裁定（按预注册 EC-A6）",
        "",
        f"**{route['branch']}** — {route['verdict']}",
        "",
        f"- route a 代价：{route['cost_comparison']['route_a']}",
        f"- route b 代价：{route['cost_comparison']['route_b']}",
        "",
        "## 与 r2 的冲突（待报告修订）",
        "",
    ]
    lines += [f"- {item}" for item in result["conflicts_with_r2"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
