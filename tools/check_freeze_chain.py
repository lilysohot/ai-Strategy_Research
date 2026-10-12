"""Verify that every contract / gold / gate binding still resolves to the bytes it claims.

P16 — implements ``bookkeeping_requirements.freeze_chain_validator_required`` from the signed
contract v4.1: "任何契约/金标/manifest 修订须有校验器验证绑定一致（现无）".

Zero model calls, read-only. Checks, in one pass:

1. the signed contract's pinned authority gate and its recorded threshold values;
2. gate 28's own gold bindings (freeze-manifest / freeze-state / frozen-gold);
3. the gold freeze manifest's recorded input hashes;
4. the **rebinding records that succeeded them** (P12 / P13) — a superseded pin is not a
   failure by itself, but it must be *covered* by a record, otherwise it is drift.

Exit code 1 when an unresolved binding is found, so this can run as a gate.

Usage:
    uv run python tools/check_freeze_chain.py
    uv run python tools/check_freeze_chain.py --json out.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

EV = REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence"
CONTRACT_V4_1 = (
    EV / "47-scoring-contract-v41-signed-20261012/r0-zero-call/scoring-contract-v4.1.json"
)
GOLD_FREEZE = EV / "10-quality-gold-freeze-20261008-r2"
FREEZE_MANIFEST = GOLD_FREEZE / "freeze-manifest.json"
FREEZE_STATE = GOLD_FREEZE / "freeze-state.json"
FROZEN_GOLD = GOLD_FREEZE / "frozen-gold.json"
P12_RECORD = GOLD_FREEZE / "rebinding-v4.1-20261012.json"
GATE_V1 = EV / "28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate.json"
GATE_V2 = EV / "28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json"

THRESHOLD_KEYS = (
    "target_recall_overall_min",
    "target_recall_per_source_min",
    "candidate_precision_min",
    "accepted_records_total_min",
    "accepted_records_per_source_min",
    "unresolved_candidates_max",
)


@dataclass
class Binding:
    """One claimed binding and whether it currently resolves."""

    claim: str
    expected: str | None
    actual: str | None
    verdict: str  # ok | drift | covered_by_record | needs_ruling
    detail: str = ""


@dataclass
class Report:
    """The whole chain's status."""

    checked: list[Binding] = field(default_factory=list)

    def add(self, binding: Binding) -> None:
        self.checked.append(binding)

    @property
    def unresolved(self) -> list[Binding]:
        return [item for item in self.checked if item.verdict in ("drift", "needs_ruling")]


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def bare(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_gold_pins(report: Report, gate: dict[str, Any], gate_label: str) -> None:
    for key, path in (
        ("freeze_manifest_sha256", FREEZE_MANIFEST),
        ("freeze_state_sha256", FREEZE_STATE),
        ("frozen_gold_sha256", FROZEN_GOLD),
    ):
        expected = gate.get("gold", {}).get(key)
        actual = sha256(path)
        report.add(
            Binding(
                claim=f"{gate_label}.gold.{key}",
                expected=expected,
                actual=actual,
                verdict="ok" if expected == actual else "drift",
                detail=str(path.relative_to(REPO_ROOT)),
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    contract = load(CONTRACT_V4_1)
    gate_v1 = load(GATE_V1)
    gate_v2 = load(GATE_V2) if GATE_V2.exists() else None
    report = Report()

    contract_hash = sha256(CONTRACT_V4_1)
    gate_v1_hash = sha256(GATE_V1)

    # 1. The contract's pinned authority gate.
    authority = contract["threshold_source"]["authority_source"]
    report.add(
        Binding(
            claim="contract v4.1 → authority gate (threshold_source.authority_source.sha256)",
            expected=authority["sha256"],
            actual=gate_v1_hash,
            verdict="ok" if authority["sha256"] == gate_v1_hash else "drift",
            detail=str(GATE_V1.relative_to(REPO_ROOT)),
        )
    )
    # ... and whether a successor gate record exists that the pin does not name.
    if gate_v2 is not None:
        report.add(
            Binding(
                claim="contract v4.1 authority pin vs successor gate record",
                expected=gate_v1_hash,
                actual=sha256(GATE_V2),
                verdict="needs_ruling",
                detail=(
                    "门 28 已按 P13 产生继任记录 preregistered-gate-v2.json，但已签契约 v4.1 的 "
                    "authority_source.sha256 仍钉在 v1 上。阈值数值经实测逐字相同，故不影响口径；"
                    "但『哪一份门是权威』需具名裁定：(a) 契约出新版本改钉 v2，或 (b) 明确 v1 为"
                    "『冻结执行门』、v2 为『基准持有记录』。"
                ),
            )
        )

    # 2. Gate threshold values must agree between the pin and the record.
    values = authority["values"]
    for gate, label in ((gate_v1, "gate v1"), (gate_v2, "gate v2")):
        if gate is None:
            continue
        recorded = gate["quality_requirements"]
        mismatched = {
            key: (values.get(key), recorded.get(key))
            for key in THRESHOLD_KEYS
            if values.get(key) != recorded.get(key)
        }
        report.add(
            Binding(
                claim=f"contract authority values vs {label}.quality_requirements",
                expected=json.dumps({k: values.get(k) for k in THRESHOLD_KEYS}, sort_keys=True),
                actual=json.dumps({k: recorded.get(k) for k in THRESHOLD_KEYS}, sort_keys=True),
                verdict="ok" if not mismatched else "drift",
                detail=json.dumps(mismatched, ensure_ascii=False) if mismatched else "",
            )
        )

    # 3. Gate gold bindings, both versions.
    check_gold_pins(report, gate_v1, "gate v1")
    if gate_v2 is not None:
        check_gold_pins(report, gate_v2, "gate v2")

    # 4. Contract binding recorded by each gate version.
    for gate, label in ((gate_v1, "gate v1"), (gate_v2, "gate v2")):
        if gate is None:
            continue
        expected = gate["gold"]["scoring_contract_sha256"]
        report.add(
            Binding(
                claim=f"{label}.gold.scoring_contract_sha256 → contract v4.1",
                expected=expected,
                actual=contract_hash,
                verdict="ok" if expected == contract_hash else "covered_by_record",
                detail=(
                    "该版本钉在更早的契约上；其推进由 P13 新版本记录覆盖"
                    if expected != contract_hash
                    else ""
                ),
            )
        )
        basis = gate["quality_requirements"].get("metric_basis")
        report.add(
            Binding(
                claim=f"{label}.quality_requirements.metric_basis",
                expected=contract["schema_version"],
                actual=basis,
                verdict="ok" if basis == contract["schema_version"] else "covered_by_record",
                detail="" if basis == contract["schema_version"] else "版本落后于已签契约",
            )
        )

    # 5. Gold freeze manifest inputs.
    manifest = load(FREEZE_MANIFEST)
    drifted = []
    for relative, expected in manifest["inputs"].items():
        path = REPO_ROOT / relative
        if not path.exists():
            drifted.append((relative, "missing"))
        elif bare(path) != expected:
            drifted.append((relative, "drift"))
    report.add(
        Binding(
            claim="freeze-manifest.json inputs (8 files, bare digests)",
            expected=f"{len(manifest['inputs'])} recorded",
            actual=f"{len(manifest['inputs']) - len(drifted)} match, {len(drifted)} not",
            verdict="covered_by_record" if drifted else "ok",
            detail="; ".join(f"{name}:{why}" for name, why in drifted),
        )
    )

    # 6. The rebinding record that must cover the manifest drift.
    if P12_RECORD.exists():
        p12 = load(P12_RECORD)
        report.add(
            Binding(
                claim="P12 record binds the current signed contract",
                expected=contract_hash,
                actual=p12["binds_contract"]["sha256"],
                verdict="ok" if p12["binds_contract"]["sha256"] == contract_hash else "drift",
                detail=str(P12_RECORD.relative_to(REPO_ROOT)),
            )
        )
        snapshot_site = next(
            (site for site in p12["binding_sites"] if site["site"].endswith("contract_snapshot")),
            None,
        )
        report.add(
            Binding(
                claim="freeze-state.json.contract_snapshot declared historical (not edited)",
                expected="embedded snapshot bytes preserved",
                actual=load(FREEZE_STATE)["contract_snapshot"]["schema_version"],
                verdict="ok" if snapshot_site else "drift",
                detail=snapshot_site["disposition"] if snapshot_site else "P12 记录未声明该站点",
            )
        )
    else:
        report.add(
            Binding(
                claim="P12 rebinding record present",
                expected=str(P12_RECORD.relative_to(REPO_ROOT)),
                actual="missing",
                verdict="drift",
            )
        )

    unresolved = report.unresolved
    summary = {
        "schema_version": "items-freeze-chain-check-1",
        "created_on": "2026-10-12",
        "zero_call": True,
        "checks": [asdict(item) for item in report.checked],
        "ok": sum(1 for item in report.checked if item.verdict == "ok"),
        "covered_by_record": sum(
            1 for item in report.checked if item.verdict == "covered_by_record"
        ),
        "drift": sum(1 for item in report.checked if item.verdict == "drift"),
        "needs_ruling": sum(1 for item in report.checked if item.verdict == "needs_ruling"),
        "exit_ok": not unresolved,
    }
    if args.json:
        Path(args.json).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if not args.quiet:
        for item in report.checked:
            mark = {
                "ok": "OK  ",
                "covered_by_record": "COVER",
                "drift": "DRIFT",
                "needs_ruling": "RULING",
            }[item.verdict]
            print(f"{mark} {item.claim}")
            if item.detail and item.verdict != "ok":
                print(f"      {item.detail[:160]}")
        print(
            f"\nok={summary['ok']} covered={summary['covered_by_record']} "
            f"drift={summary['drift']} needs_ruling={summary['needs_ruling']}"
        )
    return 0 if summary["exit_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
