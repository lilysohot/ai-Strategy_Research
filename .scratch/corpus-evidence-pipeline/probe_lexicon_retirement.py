"""Deterministic, model-free probe for retiring the overfit boundary lexicon.

Measures what retiring the overfit cues does to the frozen R2 development
obligations *before* any model call is spent.  Two retirement scopes are
reported so the budget can choose one:

* ``retire_chinese_domain``: drop ``_DOMAIN_BOUNDARY_CUES`` only;
* ``retire_all_overfit``: drop ``_DOMAIN_BOUNDARY_CUES`` and
  ``_SAMPLE_SPECIFIC_BOUNDARY_PATTERNS``.

Per sample and per scope it reports segment/slot/packet/batch counts and a
strict "obligation coverage" diagnostic: whether each frozen gold item's
evidence quote is fully contained in a single candidate slot.  Coverage is a
faithfulness *diagnostic*, not the acceptance scorer (the scorer matches quotes
with a fuzzy ratio), so it only ever blocks, never authorises.

It also reports the overfit-cue hit rate per 1000 characters for the four
development materials and for an out-of-gold stress material, which is the only
model-free signal this budget can produce about the overfit claim itself.

No LLM, no network, no writes unless ``--out`` is given.  Idempotent: output is
sorted and carries no wall-clock timestamp.  The reconstructed pattern is
asserted equal to the production regex with the retired cues removed, so the
probe cannot silently drift from ``material_semantics``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import plugins.corpus.material_semantics as ms
from plugins.corpus.evidence import EvidenceDocument
from plugins.corpus.evidence_pipeline import build_evidence_run

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "data/corpus/.audit/r1_material_gold_v1_20260913.json"
STRESS = ROOT / "data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx"
PACKET_CHARS = 3000
BATCH_CAPACITY_OPTIONS = ((8, 30), (8, 32), (16, 64))
RETIREMENT_SCOPES = (
    "retire_sample_specific_only",
    "retire_chinese_domain",
    "retire_all_overfit",
)
SCOPES = ("current", *RETIREMENT_SCOPES)


def build_boundary_pattern(
    domain_cues: tuple[str, ...], sample_patterns: tuple[str, ...]
) -> str:
    """Rebuild ``_ATOMIC_BOUNDARY_PATTERN`` with the domain/sample parts injected."""
    cue = "|".join(
        (
            *ms._BOUNDARY_NEGATION_TOKENS,
            *ms._GENERAL_BOUNDARY_CUES,
            r"(?:Q[1-4]|H[12])?预计",
            *domain_cues,
            r"(?:Q[1-4]|H[12])\b",
        )
    )
    alternatives = [
        r"[。！？；：:]\s*",
        r"\n{2,}",
        r"\.(?=\s+[A-Z0-9])\s*",
        r"\n(?=\s*(?:(?:\d+|[一二三四五六七八九十百]+)[、]|"
        r"(?:\d+|[一二三四五六七八九十百]+)[.．](?=\s)|"
        r"(?:风险提示|总结|摘要|事项|评论|投资建议|目标价|当前价|主持人|专家|投资者|问|答)\s*[：:]))",
        r"，(?=\s*(?:" + cue + "))",
        r"、(?=[^。；\n]{0,24}(?:不及预期|加剧|恶化|下行|失败|疲软|风险))",
        *sample_patterns,
    ]
    return "|".join(alternatives)


ASSERT_CURRENT = build_boundary_pattern(
    ms._DOMAIN_BOUNDARY_CUES, ms._SAMPLE_SPECIFIC_BOUNDARY_PATTERNS
)
if ASSERT_CURRENT != ms._ATOMIC_BOUNDARY_PATTERN:
    raise AssertionError("probe pattern reconstruction drifted from the production regex")

SCOPE_CUES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "current": (ms._DOMAIN_BOUNDARY_CUES, ms._SAMPLE_SPECIFIC_BOUNDARY_PATTERNS),
    "retire_sample_specific_only": (ms._DOMAIN_BOUNDARY_CUES, ()),
    "retire_chinese_domain": ((), ms._SAMPLE_SPECIFIC_BOUNDARY_PATTERNS),
    "retire_all_overfit": ((), ()),
}
SCOPE_RES: dict[str, re.Pattern[str]] = {
    scope: re.compile(build_boundary_pattern(*cues), re.I) for scope, cues in SCOPE_CUES.items()
}
DOMAIN_HIT_RE = re.compile(r"，(?=\s*(?:" + "|".join(ms._DOMAIN_BOUNDARY_CUES) + "))")
SAMPLE_HIT_RE = re.compile("|".join(ms._SAMPLE_SPECIFIC_BOUNDARY_PATTERNS), re.I)


def normalized(value: object) -> str:
    return "".join(str(value or "").lower().split())


def structure_and_slots(document: EvidenceDocument, *, scope: str) -> tuple[Any, ...]:
    original = ms._ATOMIC_BOUNDARY_RE
    ms._ATOMIC_BOUNDARY_RE = SCOPE_RES[scope]
    try:
        structure = ms.build_material_structure(document)
        return ms.build_candidate_slots(document, structure)
    finally:
        ms._ATOMIC_BOUNDARY_RE = original


def coverage(items: list[dict[str, Any]], slots: tuple[Any, ...]) -> list[dict[str, Any]]:
    texts = [normalized(slot.text) for slot in slots]
    return [
        {
            "item_id": item["item_id"],
            "critical": bool(item.get("critical")),
            "covered": any(normalized(item["evidence"][0]["quote"]) in text for text in texts),
        }
        for item in items
    ]


def cue_hit_rates(document: EvidenceDocument) -> dict[str, Any]:
    text = "\n".join(packet.text for packet in document.packets if packet.status == "available")
    per_1k = 1000.0 / len(text) if text else 0.0
    domain = len(DOMAIN_HIT_RE.findall(text))
    sample = len(SAMPLE_HIT_RE.findall(text))
    return {
        "chars": len(text),
        "domain_boundary_hits": domain,
        "sample_boundary_hits": sample,
        "domain_hits_per_1k_chars": round(domain * per_1k, 3),
        "sample_hits_per_1k_chars": round(sample * per_1k, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, default=GOLD)
    parser.add_argument("--stress", type=Path, default=STRESS)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-write", action="store_true", dest="no_write")
    args = parser.parse_args()

    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    samples = [s for s in gold["samples"] if s["split"] == "development"]

    report: dict[str, Any] = {
        "probe": "lexicon-retirement",
        "gold": str(args.gold.relative_to(ROOT)),
        "packet_chars": PACKET_CHARS,
        "retired_cues": {
            "chinese_domain": list(ms._DOMAIN_BOUNDARY_CUES),
            "sample_specific": list(ms._SAMPLE_SPECIFIC_BOUNDARY_PATTERNS),
        },
        "batch_capacity_options": [list(pair) for pair in BATCH_CAPACITY_OPTIONS],
        "coverage_definition": "gold evidence quote whitespace-stripped, case-folded, "
        "fully contained in one candidate slot text (strict diagnostic, not the scorer)",
        "samples": [],
        "cue_hit_rates": {},
    }

    for sample in samples:
        source = ROOT / sample["source_path"]
        pages = tuple(sample["scoped_pages"]) if "scoped_pages" in sample else None
        document = build_evidence_run(
            source, pages=pages, packet_chars=PACKET_CHARS
        ).document
        by_scope = {scope: structure_and_slots(document, scope=scope) for scope in SCOPES}
        current_ids = {slot.candidate_slot_id for slot in by_scope["current"]}
        current_covered = {
            row["item_id"]
            for row in coverage(sample["items"], by_scope["current"])
            if row["covered"]
        }
        entry: dict[str, Any] = {
            "sample_id": sample["sample_id"],
            "source_rev": sample["source_rev"],
            "material_type": sample["material_type"],
            "split": sample["split"],
            "gold_items": len(sample["items"]),
            "gold_critical_items": sum(1 for item in sample["items"] if item.get("critical")),
            "scopes": {},
        }
        for scope in SCOPES:
            slots = by_scope[scope]
            slot_ids = {slot.candidate_slot_id for slot in slots}
            rows = coverage(sample["items"], slots)
            entry["scopes"][scope] = {
                "slots": len(slots),
                "slots_removed_vs_current": len(current_ids - slot_ids),
                "slots_added_vs_current": len(slot_ids - current_ids),
                "packets": len({slot.packet_id for slot in slots}),
                "covered": sum(1 for row in rows if row["covered"]),
                "covered_critical": sum(1 for row in rows if row["covered"] and row["critical"]),
                "uncovered_critical": [
                    row["item_id"] for row in rows if not row["covered"] and row["critical"]
                ],
                "coverage_lost_vs_current": sorted(
                    current_covered - {row["item_id"] for row in rows if row["covered"]}
                ),
                "batch_plans": {
                    f"slots{slots_per_batch}_items{items_per_packet}": len(
                        ms.build_candidate_slot_batches(
                            slots,
                            max_slots_per_batch=slots_per_batch,
                            max_items_per_batch=items_per_packet,
                        )
                    )
                    for slots_per_batch, items_per_packet in BATCH_CAPACITY_OPTIONS
                },
            }
        report["samples"].append(entry)
        report["cue_hit_rates"][sample["sample_id"]] = cue_hit_rates(document)

    if args.stress.is_file():
        stress_document = build_evidence_run(args.stress, packet_chars=PACKET_CHARS).document
        report["cue_hit_rates"]["stress:optical-unlabelled"] = {
            "source": str(args.stress.relative_to(ROOT)),
            "model_calls_allowed": 0,
            **cue_hit_rates(stress_document),
        }

    for scope in RETIREMENT_SCOPES:
        report[f"{scope}_coverage_lost_total"] = sorted(
            item_id
            for sample in report["samples"]
            for item_id in sample["scopes"][scope]["coverage_lost_vs_current"]
        )
        report[f"{scope}_planned_calls_slots16_items64"] = sum(
            sample["scopes"][scope]["batch_plans"]["slots16_items64"]
            for sample in report["samples"]
        )

    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out is not None and not args.no_write:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
