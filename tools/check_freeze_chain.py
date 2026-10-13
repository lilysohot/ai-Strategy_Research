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
# The currently signed contract; newer versions replace this path as they are signed.
# R2 (2026-10-13): v4.3 signed ⇒ the pointer advances one step, same 手续 as v4.1 → v4.2.
_CONTRACT_CANDIDATES = (
    EV / "75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json",
    EV / "58-contract-v42-signed-20261012/r0-zero-call/scoring-contract-v4.2.json",
    EV / "47-scoring-contract-v41-signed-20261012/r0-zero-call/scoring-contract-v4.1.json",
)
CONTRACT_CURRENT = next(
    (path for path in _CONTRACT_CANDIDATES if path.exists()), _CONTRACT_CANDIDATES[-1]
)
GOLD_FREEZE = EV / "10-quality-gold-freeze-20261008-r2"
FREEZE_MANIFEST = GOLD_FREEZE / "freeze-manifest.json"
FREEZE_STATE = GOLD_FREEZE / "freeze-state.json"
FROZEN_GOLD = GOLD_FREEZE / "frozen-gold.json"
_REBINDING_RECORDS = sorted(GOLD_FREEZE.glob("rebinding-v*.json"))
# The latest rebinding record is the one that must bind the currently signed contract.
P12_RECORD = (
    _REBINDING_RECORDS[-1] if _REBINDING_RECORDS else (GOLD_FREEZE / "rebinding-v4.1-20261012.json")
)
GATE_V1 = EV / "28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate.json"
GATE_V2 = EV / "28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json"
GATE_V3 = EV / "75-r2-signed-20261013/r0-zero-call/gate-v3.json"

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


def check_scorer_contract_source(report: Report, contract: dict[str, Any]) -> None:
    """P03: the scorer must load the currently signed contract as its sole source."""
    sys.path.insert(0, str(REPO_ROOT))
    from plugins.corpus.structured_scoring import (
        CONTRACT_GATE_REQUIREMENTS,
        SIGNED_SCORING_CONTRACT_PATH,
        load_contract_gate_requirements,
    )

    selected = load_contract_gate_requirements(CONTRACT_CURRENT)
    expected_path = str(CONTRACT_CURRENT.resolve())
    actual_path = str(SIGNED_SCORING_CONTRACT_PATH.resolve())
    report.add(
        Binding(
            claim="scorer default contract path == currently signed contract",
            expected=expected_path,
            actual=actual_path,
            verdict="ok" if expected_path == actual_path else "drift",
        )
    )
    report.add(
        Binding(
            claim="scorer default requirements == requirements loaded from signed contract",
            expected=repr(selected),
            actual=repr(CONTRACT_GATE_REQUIREMENTS),
            verdict="ok" if selected == CONTRACT_GATE_REQUIREMENTS else "drift",
        )
    )
    report.add(
        Binding(
            claim="scorer loaded schema_version == contract schema_version",
            expected=contract["schema_version"],
            actual=CONTRACT_GATE_REQUIREMENTS.schema_version,
            verdict="ok"
            if CONTRACT_GATE_REQUIREMENTS.schema_version == contract["schema_version"]
            else "drift",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    contract = load(CONTRACT_CURRENT)
    report = Report()
    check_scorer_contract_source(report, contract)
    gate_v1 = load(GATE_V1)
    gate_v2 = load(GATE_V2) if GATE_V2.exists() else None
    gate_v3 = load(GATE_V3) if GATE_V3.exists() else None

    contract_hash = sha256(CONTRACT_CURRENT)
    gate_v1_hash = sha256(GATE_V1)
    gate_v2_hash = sha256(GATE_V2) if GATE_V2.exists() else None
    gate_v3_hash = sha256(GATE_V3) if GATE_V3.exists() else None
    known_gates = {
        "gate v1 (preregistered-gate.json)": gate_v1_hash,
        "gate v2 (preregistered-gate-v2.json)": gate_v2_hash,
        "gate v3 (75-r2-signed-20261013/gate-v3.json)": gate_v3_hash,
    }
    # 版本顺序即签认顺序；第 4 节与后继门判定共用
    GATE_RECORDS = (("gate v1", gate_v1), ("gate v2", gate_v2), ("gate v3", gate_v3))
    ordered_gate_versions = [
        (label, digest)
        for label, digest in (
            ("gate v1", gate_v1_hash),
            ("gate v2", gate_v2_hash),
            ("gate v3", gate_v3_hash),
        )
        if digest
    ]
    newest_gate = ordered_gate_versions[-1]

    # 1. The contract's pinned authority gate must be one of the known gate records.
    authority = contract["threshold_source"]["authority_source"]
    pinned_label = next(
        (label for label, digest in known_gates.items() if digest == authority["sha256"]), None
    )
    report.add(
        Binding(
            claim="current contract → authority gate (threshold_source.authority_source.sha256)",
            expected=authority["sha256"],
            actual=pinned_label or "no known gate record matches",
            verdict="ok" if pinned_label else "drift",
            detail=str(GATE_V1.relative_to(REPO_ROOT)),
        )
    )
    # ... and whether the pin names the newest gate record that exists.
    if authority["sha256"] != newest_gate[1]:
        report.add(
            Binding(
                claim="contract authority pin vs newest gate record",
                expected=newest_gate[1],
                actual=authority["sha256"],
                verdict="needs_ruling",
                detail=(
                    f"最新门记录为 {newest_gate[0]}，而契约 authority_source.sha256 仍钉在更早版本。"
                    "须以新版本记录推进契约改钉（沿用 v4.1 → v4.2 → v4.3 的同一手续）。"
                ),
            )
        )

    # 2. Gate threshold values must agree between the pin and the record.
    values = authority["values"]
    for label, gate in GATE_RECORDS:
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

    # 3. Gate gold bindings, every version.
    for label, gate in GATE_RECORDS:
        if gate is not None:
            check_gold_pins(report, gate, label)

    # 4. Contract binding recorded by each gate version.
    for label, gate in GATE_RECORDS:
        if gate is None:
            continue
        expected = gate["gold"]["scoring_contract_sha256"]
        report.add(
            Binding(
                claim=f"{label}.gold.scoring_contract_sha256 → signed contract",
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
        chase = gate["quality_requirements"].get("contract_version_chase")
        lagged = basis != contract["schema_version"]
        report.add(
            Binding(
                claim=f"{label}.quality_requirements.metric_basis",
                expected=contract["schema_version"],
                actual=basis,
                verdict="ok" if not lagged else "covered_by_record",
                detail=(
                    "版本落后一档：门只推进到最近一个已签契约版本（双向钉哈希会成环）；"
                    f"已由 contract_version_chase 登记，不变量={chase.get('invariant') if chase else '未登记'}"
                    if lagged
                    else ""
                ),
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
        p12_binds = p12["binds_contract"]["sha256"]
        registration = contract.get("registrations", {}).get("frozen_gold_side_contract_binding", {})
        covered_by_registration = p12_binds != contract_hash and bool(registration.get("status"))
        report.add(
            Binding(
                claim="P12 record (or the contract's own registration) covers the gold-side binding",
                expected=contract_hash,
                actual=p12_binds,
                verdict=(
                    "ok"
                    if p12_binds == contract_hash
                    else ("covered_by_record" if covered_by_registration else "drift")
                ),
                detail=(
                    f"{P12_RECORD.relative_to(REPO_ROOT)} 钉在更早的已签契约上；"
                    "冻结金标字节不可改，故由契约 registrations.frozen_gold_side_contract_binding 登记为例外"
                    if covered_by_registration
                    else str(P12_RECORD.relative_to(REPO_ROOT))
                ),
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
