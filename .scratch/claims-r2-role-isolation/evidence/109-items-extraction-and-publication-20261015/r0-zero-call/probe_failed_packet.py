"""Capture the raw model response of ONE discarded packet (109 号 root-cause probe).

Round-1 packets were discarded by the strict JSONL validator with
"role response contains an unsupported JSONL record" (material_semantics.py:4350), and raw
responses are not persisted (adapter.py:239 "Never propagate provider text"). This probe re-runs
exactly the slots of one discarded packet through the real extraction path, with the dispatch
capturing the raw response to disk before anything else sees it. One model call, a few k tokens.

Usage:
    python probe_failed_packet.py <slug> <packet_id_prefix> [--out probe-capture]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.material_semantics import MATERIAL_SELECTOR_JSONL_VERSION  # noqa: E402
from plugins.corpus.structured.adapter import ExtractionAdapter  # noqa: E402
from plugins.corpus.structured.roles import (  # noqa: E402
    RoleRequest,
    execute_material_items_role,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402

FREEZE_28 = ROOT / "evidence/28-items-only-quality-gate-20261010/r0-zero-call"


def _load_freeze_28() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "freeze_items_only_plan_28", FREEZE_28 / "freeze_items_only_plan.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("packet_id_prefix")
    parser.add_argument("--out", type=Path, default=HERE / "probe-capture")
    args = parser.parse_args()

    freeze_28 = _load_freeze_28()
    source = next(item for item in freeze_28.scoped_sources() if item["slug"] == args.slug)
    snapshot: EvidenceSnapshot = source["snapshot"]
    snapshot.verify_identity()

    # The discarded packet's slots, read from the round-1 payload (already on disk, zero call).
    round1 = json.loads(
        _round1_payload_path(args.slug, args.packet_id_prefix).read_text(encoding="utf-8")
    )
    slots = sorted(
        {
            slot["candidate_slot_id"]
            for slot in round1["candidate_slots"]
            if slot["packet_id"].startswith(args.packet_id_prefix)
        }
    )
    if not slots:
        raise SystemExit(f"no round-1 slots found for packet {args.packet_id_prefix!r}")

    config = freeze_28.config()
    capture: list[dict[str, Any]] = []
    adapter = ExtractionAdapter(
        role_binding(config, MATERIAL_SELECTOR_JSONL_VERSION),
        authorize=lambda intent: "probe-attempt-0001",
        transport_factory=None,
    )

    def dispatch(request: RoleRequest) -> str:
        response = adapter(request.prompt)
        text = response if isinstance(response, str) else str(response)
        capture.append({"prompt_chars": len(request.prompt), "raw_response": text})
        return text

    result = execute_material_items_role(
        snapshot,
        task_id="probe:109-root-cause",
        protocol=MATERIAL_SELECTOR_JSONL_VERSION,
        max_calls=1,
        max_items_per_packet=64,
        max_slots_per_batch=24,
        max_estimated_tokens_per_batch=8192,
        material_type=None,
        candidate_slot_ids=slots,
        dispatch=dispatch,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "raw-response.json").write_text(
        json.dumps(capture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run = result.payload
    packet_report = [
        {"packet_id": p.packet_id[:12], "status": p.status, "reasons": list(p.reasons)}
        for p in run.packet_runs
    ]
    (args.out / "probe-report.json").write_text(
        json.dumps(
            {
                "slug": args.slug,
                "packet_prefix": args.packet_id_prefix,
                "slots": slots,
                "probe_run": {
                    "execution_status": result.artifact.execution_status,
                    "protocol_status": result.artifact.protocol_status,
                    "items": len(run.understanding.items),
                },
                "packet_runs": packet_report,
                "model_calls": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"captured": len(capture), "packets": packet_report}, ensure_ascii=False))
    return 0


def role_binding(config: Any, protocol: str) -> Any:
    from plugins.corpus.structured.ledger import RoleBinding

    return RoleBinding(role="material_items", protocol=protocol, config=config)


def _round1_payload_path(slug: str, packet_prefix: str) -> Path:
    base = HERE / "items-reextract-plan-freeze" / slug / "live-store"
    connection = None
    import sqlite3

    connection = sqlite3.connect(base / "index/structured.sqlite3")
    digest = str(
        connection.execute(
            "SELECT payload_object_sha256 FROM tasks WHERE role='material_items'"
        ).fetchone()[0]
    ).removeprefix("sha256:")
    connection.close()
    return base / "objects/sha256" / digest[:2] / f"{digest}.json"


if __name__ == "__main__":
    raise SystemExit(main())
