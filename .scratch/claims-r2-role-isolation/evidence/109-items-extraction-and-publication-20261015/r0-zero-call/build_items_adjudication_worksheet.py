"""Stage 2 + stage 3 entry of the 109-号 items re-extraction: gates, then worksheet.

Stage 2 (zero-call): the two pre-registered execution-validity gates are measured on the new pool
with rules read from the signed pre-registration (not hardcoded) — a failed gate stops the run
before the adjudication round and this script writes ``stage2-failed.json`` instead of a worksheet.

Stage 3: the worksheet the named human fills — one row per material_items candidate,
``reviewer``/``adjudicator`` left blank, ``review_status="pending_named_human_signoff"``, plus the
92-号 C1 pending-coverage checklist (29 role-external claims candidates owned by material_items —
covered here or recorded ``no_candidate``, never dropped). Gold is never read here.

Usage:
    python build_items_adjudication_worksheet.py [--freeze DIR] [--out DIR] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import assert_writable, write_once  # noqa: E402

PREREG = HERE / "items-reextraction-preregistration-v2.json"
C1_REGISTRATION = (
    ROOT
    / "evidence/92-claims-scope-registration-20261014/r0-zero-call/claims-scope-registration.json"
)
CONDITION_PATTERN = re.compile(r"如果|只要|除非|前提|取决于")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display(path: Path) -> str:
    """Repo-relative when possible; tests patch these constants to temp dirs."""
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pool_of(store: Path) -> list[dict[str, Any]]:
    """Every material_items candidate in one run's store, in task then item order."""
    return task_stats(store)["candidates"]


def task_stats(store: Path) -> dict[str, Any]:
    """Candidates plus the counters the stage-2 gates and report-onlys read.

    v2 semantics (signed prereg): the pool is collected from *every* task payload regardless of
    the task terminal state — a semantic-controller discard marks the task failed without
    invalidating the items it did extract. Only an attempt-level outcome_unknown is an execution
    incident; the pool itself stays a report-only view of what actually came back.
    """
    index = store / "index/structured.sqlite3"
    if not index.exists():
        raise SystemExit(f"refusing to build a worksheet: no store at {store}")
    connection = sqlite3.connect(index)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT execution_status, protocol_status, payload_object_sha256 FROM tasks "
            "WHERE role = 'material_items'"
        ).fetchall()
        attempt_rows = connection.execute("SELECT execution_status FROM attempts").fetchall()
    finally:
        connection.close()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not row["payload_object_sha256"]:
            continue
        digest = str(row["payload_object_sha256"]).removeprefix("sha256:")
        payload = json.loads(
            (store / "objects/sha256" / digest[:2] / f"{digest}.json").read_text(encoding="utf-8")
        )
        speakers = {
            speaker["speaker_id"]: speaker for speaker in payload["understanding"]["speakers"]
        }
        for item in payload["understanding"]["items"]:
            candidates.append({"item": item, "speaker": speakers.get(item.get("speaker_ref"))})
    return {
        "candidates": candidates,
        "failed_tasks": sum(1 for row in rows if row["execution_status"] != "succeeded"),
        "attempts_outcome_unknown": sum(
            1 for row in attempt_rows if row["execution_status"] == "outcome_unknown"
        ),
        "protocol_status_distribution": dict(Counter(str(row["protocol_status"]) for row in rows)),
    }


def canonical_observed(item: dict[str, Any], speaker: dict[str, Any] | None) -> dict[str, Any]:
    """The ten-field projection the human adjudicates.

    ``condition``/``attribution``/``factuality`` are derived with the same predicates as the store's
    layer-B records (``structured/store.py::_material_records``); ``source_stance`` has no carrier
    (契约已登记的零载体字段) and stays ``None`` for the human.
    """
    text = str(item.get("text") or "")
    statement_role = item.get("statement_role")
    if statement_role == "condition":
        condition: str | None = "conditional"
    elif CONDITION_PATTERN.search(text):
        condition = None
    else:
        condition = "unconditional"
    if speaker is not None and speaker.get("role") == "document_voice":
        attribution: str | None = "document_voice"
    elif speaker is not None and speaker.get("identity_status") == "explicit":
        attribution = speaker.get("display_name")
    else:
        attribution = None
    evidence = (item.get("evidence") or [{}])[0]
    return {
        "proposition": text,
        "semantic_type": item.get("semantic_type"),
        "statement_role": statement_role,
        "speech_role": item.get("speech_role"),
        "perspective": item.get("perspective"),
        "polarity": item.get("polarity"),
        "speaker_ref": item.get("speaker_ref"),
        "attribution": attribution,
        "condition": condition,
        "source_stance": None,
        "factuality": item.get("semantic_type"),
        "evidence_locator": evidence.get("locator"),
        "evidence_quote": evidence.get("quote"),
    }


def evaluate_rule(rule: str, value: int | None) -> bool:
    """Evaluate a signed rule literally; an unknown rule refuses (fail-closed)."""
    match = re.fullmatch(r"(==|>=|<=)\s*(-?\d+)", rule.strip())
    if match is None or value is None:
        raise SystemExit(f"unsupported signed stage2 rule: {rule!r} (value={value!r})")
    operator, number = match.group(1), int(match.group(2))
    return {"==": value == number, ">=": value >= number, "<=": value <= number}[operator]


def measure(
    items_by_slug: dict[str, list[dict[str, Any]]],
    stats_by_slug: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidates_total = sum(len(items) for items in items_by_slug.values())
    return {
        "sources_with_candidates": sum(1 for items in items_by_slug.values() if items),
        "attempts_outcome_unknown": sum(
            int(stats["attempts_outcome_unknown"]) for stats in stats_by_slug.values()
        ),
        "material_items_tasks_failed": sum(
            int(stats["failed_tasks"]) for stats in stats_by_slug.values()
        ),
        "candidates_total": candidates_total,
        "candidates_per_source": {slug: len(items) for slug, items in items_by_slug.items()},
        "distinct_slots_with_candidates": len(
            {
                item["item"].get("evidence", [{}])[0].get("locator")
                for items in items_by_slug.values()
                for item in items
            }
        ),
        "protocol_status_distribution": {
            slug: stats["protocol_status_distribution"] for slug, stats in stats_by_slug.items()
        },
    }


def apply_signed_gates(measured: dict[str, Any]) -> dict[str, Any]:
    prereg = load(PREREG)
    if prereg.get("status") != "frozen_before_execution":
        raise SystemExit(f"refusing to measure: pre-registration is {prereg.get('status')!r}")
    verdicts: list[dict[str, Any]] = []
    for name, spec in prereg["stage2_gates"]["gates"].items():
        if not spec.get("gating"):
            continue
        value = measured.get(name)
        verdicts.append(
            {
                "gate": name,
                "rule": spec["rule"],
                "measured": value,
                "passed": evaluate_rule(str(spec["rule"]), value),
            }
        )
    return {
        "stage2_gates_source": display(PREREG),
        "prereg_sha256": sha256(PREREG),
        "verdicts": verdicts,
        "passed": all(item["passed"] for item in verdicts),
    }


def c1_checklist(prereg: dict[str, Any]) -> list[dict[str, Any]]:
    binding = prereg["adjudication_clause"]["c1_pending_coverage"]
    if binding["sha256"] != sha256(C1_REGISTRATION):
        raise SystemExit("refusing: C1 registration hash does not match the signed binding")
    registration = load(C1_REGISTRATION)
    entries = [
        entry
        for entry in registration["entries"]
        if entry.get("owner_role") == "material_items" and entry.get("status") == "pending_coverage"
    ]
    if len(entries) != int(binding["count"]):
        raise SystemExit(
            f"refusing: C1 checklist has {len(entries)} entries, signed binding says {binding['count']}"
        )
    return [
        {
            "c1_candidate_id": entry["candidate_id"],
            "claim_text": entry["claim_text"],
            "owner_source_id": entry["owner_source_id"],
            "role_external_reason": entry["role_external_reason"],
            "covered_by_candidate_id": None,
            "disposition": None,
        }
        for entry in entries
    ]


def build(freeze: Path, out: Path) -> dict[str, Any]:
    summary_path = freeze / "execution-summary.json"
    manifest_path = freeze / "manifest.json"
    if not summary_path.exists():
        raise SystemExit(f"refusing to build a worksheet: {summary_path} 不存在（先跑 execute）")
    manifest = load(manifest_path)
    summary = load(summary_path)
    if summary.get("budget_exceeded"):
        raise SystemExit("refusing to build a worksheet: the run exceeded its token ceiling")

    items_by_slug: dict[str, list[dict[str, Any]]] = {}
    stats_by_slug: dict[str, dict[str, Any]] = {}
    for entry in manifest["entries"]:
        slug = str(entry["slug"])
        stats_by_slug[slug] = task_stats(freeze / slug / "live-store")
        items_by_slug[slug] = stats_by_slug[slug]["candidates"]

    measured = measure(items_by_slug, stats_by_slug)
    gates = apply_signed_gates(measured)

    rows: list[dict[str, Any]] = []
    for slug, items in items_by_slug.items():
        for record in items:
            item = record["item"]
            evidence = (item.get("evidence") or [{}])[0]
            rows.append(
                {
                    "candidate_id": item["item_id"],
                    "role": "material_items",
                    "run": slug,
                    "stage": "raw",
                    "source_id": next(
                        entry["source_id"] for entry in manifest["entries"] if entry["slug"] == slug
                    ),
                    "original_candidate": {
                        **item,
                        "speaker": record["speaker"],
                        "source_slug": slug,
                    },
                    "canonical_observed_fields": canonical_observed(item, record["speaker"]),
                    "evidence": {
                        "locator": evidence.get("locator"),
                        "quote": evidence.get("quote"),
                    },
                    "judgement": None,
                    "matched_gold_id": None,
                    "reason": None,
                    "reviewer": None,
                    "adjudicator": None,
                    "review_status": "pending_named_human_signoff",
                }
            )

    prereg = load(PREREG)
    worksheet = {
        "schema_version": "items-reextract-adjudication-worksheet-1",
        "status": "pending_named_human_adjudication",
        "created_on": "2026-10-15",
        "model_calls": 0,
        "gold_not_exposed_to_model": True,
        "freeze": {
            "manifest": display(manifest_path),
            "manifest_sha256": sha256(manifest_path),
            "execution_summary_sha256": sha256(summary_path),
        },
        "execution": {
            "new_model_calls": summary.get("new_model_calls"),
            "authorised_ceiling_total_tokens": summary.get("authorised_ceiling_total_tokens"),
        },
        "signed_gates": gates,
        "stage2_measured": measured,
        "candidate_count": len(rows),
        "adjudication_fields_required_by_contract": [
            "candidate_id",
            "stage",
            "role",
            "source_id",
            "original_candidate",
            "judgement",
            "matched_gold_id",
            "canonical_observed_fields",
            "reviewer",
            "reason",
            "evidence",
        ],
        "instructions": (
            "逐条裁定：把 judgement 填 matched / correct_extra / incorrect / duplicate / "
            "unresolved / out_of_scope，matched 时填 matched_gold_id；reviewer 与 adjudicator "
            "具名、review_status 改 accepted。assistant 每裁完一批（20 条）即列出该批候选清单"
            "（序号/candidate_id/命题/裁定/映射金标）留档；机械预填不得替代人工校准记录。"
            "c1_pending_coverage 的 29 条逐条处置：有对应候选填 covered_by_candidate_id，"
            "无对应填 disposition=no_candidate。"
        ),
        "adjudications": rows,
        "c1_pending_coverage": c1_checklist(prereg),
    }
    return {"worksheet": worksheet, "gates": gates}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=HERE / "items-reextract-plan-freeze")
    parser.add_argument("--out", type=Path, default=HERE / "items-reextract-adjudication")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = build(args.freeze, args.out)
    measured = result["worksheet"]["stage2_measured"]
    gates = result["gates"]
    measure_payload = (
        json.dumps({"measured": measured, "signed_gates": gates}, ensure_ascii=False, indent=2)
        + "\n"
    ).encode("utf-8")

    outputs: dict[str, bytes] = {"stage2-gates.json": measure_payload}
    if gates["passed"]:
        outputs["candidate-adjudications.worksheet.json"] = (
            json.dumps(result["worksheet"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
    else:
        outputs["stage2-failed.json"] = (
            json.dumps(
                {
                    "schema_version": "items-reextract-stage2-failed-1",
                    "verdict": "轮次执行有效性未达已签止损判据",
                    "measured": measured,
                    "signed_gates": gates,
                    "consequence": "不生成工作表、不进入人工裁定",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")

    args.out.mkdir(parents=True, exist_ok=True)
    targets = {name: args.out / name for name in outputs}
    for name, target in targets.items():
        assert_writable(target, reason="109 号新池裁定工作表")
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing output {name}; use --force")
    for name, data in outputs.items():
        write_once(targets[name], data.decode("utf-8"), allow_overwrite=True)
    print(
        json.dumps(
            {
                "measured": measured,
                "passed": gates["passed"],
                "c1_entries": len(result["worksheet"]["c1_pending_coverage"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if gates["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
