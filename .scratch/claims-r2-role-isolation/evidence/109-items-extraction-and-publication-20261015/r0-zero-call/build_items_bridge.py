"""Build the items bridge inputs (109 号 P6, zero model calls).

Turns the round-3 material_items extraction run — the pool U adjudicated row by row — into the two
files the pre-existing ledger bridge consumes:

* ``items-payload.json`` — the ``MaterialRun`` of the round-3 rerun, **verbatim**: the accepted pool
  is the extracted pool;
* ``items-artifact.json`` — the upstream ``RoleArtifact`` that declares this run accepted.

Why the artifact may declare ``quality_status="accepted"``: the acceptance authority is the
xyl-signed adjudication (109 号 P4), not a machine protocol check — exactly the semantics the items
bridge already had (``_import_material_items_execution``), and which 106 号 reused for claims.

Why nothing is dropped. The round-3 worksheet carries 41 ``matched`` / 150 ``correct_extra`` /
8 ``duplicate`` / 0 ``incorrect``. Those 8 ``duplicate`` rows are **distinct extractions** whose
reason text says so ("与[60]同覆I14…为一对一约束下的重复标注"): the judgement is forced by the
scorer's one-to-one gold mapping, not by a duplicate rendering. Deleting real extracted items to
satisfy a scoring-side constraint is the anti-pattern registered in 83 号, so the full 199-item pool
is published and the decision is recorded here. Per-row evidence is checked id-for-id against the
worksheet; no gold field is read.

Usage:
    python build_items_bridge.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.material_semantics import MaterialRun  # noqa: E402
from plugins.corpus.structured.config import canonical_hash  # noqa: E402
from plugins.corpus.structured.roles import RoleArtifact, RoleCoverage  # noqa: E402
from plugins.corpus.structured.snapshot import EvidenceSnapshot  # noqa: E402
from tools.evidence_guard import assert_writable, write_once  # noqa: E402

FREEZE = HERE / "items-reextract-plan-freeze-r3"
WORKSHEET = HERE / "items-reextract-adjudication-r3/candidate-adjudications.worksheet.json"
RUNS = ("industrial-fulian-md", "optical-module-docx")
SIGNED_REASON = "xyl_signed_adjudication_2026_10_15"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def payload_of(run: str) -> tuple[dict[str, Any], Path]:
    run_dir = FREEZE / run
    connection = sqlite3.connect(
        f"file:{run_dir / 'live-store/index/structured.sqlite3'}?mode=ro", uri=True
    )
    try:
        digest = connection.execute("SELECT payload_object_sha256 FROM tasks").fetchone()[0]
    finally:
        connection.close()
    hexdigest = str(digest).removeprefix("sha256:")
    return load(
        run_dir / "live-store/objects/sha256" / hexdigest[:2] / f"{hexdigest}.json"
    ), run_dir


def build_run(run: str, judged: dict[str, str]) -> dict[str, Any]:
    run_dir = FREEZE / run
    snapshot = EvidenceSnapshot.model_validate_json((run_dir / "snapshot.json").read_text())
    plan = load(run_dir / "plan.json")
    task = next(task for task in plan["tasks"] if task["role"] == "material_items")
    raw, _ = payload_of(run)
    payload = MaterialRun.model_validate(raw)

    pool = [str(item.item_id) for item in payload.understanding.items]
    if len(pool) != len(set(pool)):
        raise SystemExit(f"refusing: {run} payload repeats an item_id")
    expected = {candidate for candidate, owner in judged.items() if owner == run}
    if set(pool) != expected:
        raise SystemExit(
            f"refusing: {run} payload/worksheet mismatch: "
            f"payload_only={sorted(set(pool) - expected)[:3]} "
            f"worksheet_only={sorted(expected - set(pool))[:3]}"
        )
    if payload.understanding.relations:
        raise SystemExit(
            f"refusing: {run} payload carries relations; the items scope excluded them"
        )

    base = RoleArtifact(
        artifact_id="sha256:" + "0" * 64,
        role="material_items",
        snapshot_id=snapshot.snapshot_id,
        task_id=task["task_id"],
        protocol=task["protocol"],
        business_contract="MaterialRun/MaterialUnderstanding",
        payload_sha256=canonical_hash(payload.model_dump(mode="json")),
        payload_media_type="application/json",
        upstream_artifact_ids=(),
        coverage=RoleCoverage(
            scoped_unit_ids=tuple(task["scoped_unit_ids"]),
            omitted_unit_ids=(),
            reason_codes=(SIGNED_REASON, "accepted_items_full_pool", "relations_not_requested"),
        ),
        execution_status="succeeded",
        protocol_status="valid",
        context_status="complete",
        quality_status="accepted",
    )
    artifact = base.model_copy(
        update={
            "artifact_id": canonical_hash(base.model_dump(mode="json", exclude={"artifact_id"}))
        }
    )
    artifact.verify_identity()
    return {
        "run": run,
        "snapshot_id": snapshot.snapshot_id,
        "source_id": snapshot.source_id,
        "build_id": snapshot.build_id,
        "protocol": task["protocol"],
        "task_id": task["task_id"],
        "items": len(pool),
        "scoped_units": len(task["scoped_unit_ids"]),
        "artifact": json.loads(artifact.model_dump_json()),
        "payload": json.loads(payload.model_dump_json()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    worksheet = load(WORKSHEET)
    rows = worksheet["adjudications"]
    judged = {str(row["candidate_id"]): str(row["run"]) for row in rows}
    tally: dict[str, int] = {}
    for row in rows:
        tally[str(row["judgement"])] = tally.get(str(row["judgement"]), 0) + 1
    dropped = [str(row["candidate_id"]) for row in rows if row["judgement"] == "incorrect"]
    if dropped:
        raise SystemExit(
            f"refusing: the worksheet carries {len(dropped)} adjudicated-incorrect rows; "
            "this builder was written for a zero-incorrect adjudication — re-decide before publishing"
        )
    results = [build_run(run, judged) for run in RUNS]

    outputs: dict[Path, str] = {}
    ledger = []
    for result in results:
        directory = HERE / f"items-bridge-{result['run']}"
        outputs[directory / "items-artifact.json"] = (
            json.dumps(result["artifact"], ensure_ascii=False, indent=2) + "\n"
        )
        outputs[directory / "items-payload.json"] = (
            json.dumps(result["payload"], ensure_ascii=False, indent=2) + "\n"
        )
        ledger.append(
            {
                "run": result["run"],
                "snapshot_id": result["snapshot_id"],
                "source_id": result["source_id"],
                "build_id": result["build_id"],
                "protocol": result["protocol"],
                "items_published": result["items"],
                "scoped_units": result["scoped_units"],
                "dropped": [],
                "artifact_id": result["artifact"]["artifact_id"],
                "payload_sha256": result["artifact"]["payload_sha256"],
            }
        )

    record = {
        "schema_version": "items-bridge-inputs-1",
        "id": "109-items-extraction-and-publication-20261015",
        "created_on": "2026-10-15",
        "model_calls": 0,
        "authority": (
            "109 号 P4 人工裁定（199/199 具名，reviewer=adjudicator=xyl）+ P5 放行签认"
            "（items-p5-release-decided.json）"
        ),
        "rule": (
            "导入 round-3 全池（matched 41 + correct_extra 150 + duplicate 8 = 199）；"
            "0 条 incorrect ⇒ 无剔除；被剔除条目清单为空且必须为空"
        ),
        "why_duplicates_retained": (
            "8 条 duplicate 的 reason 逐条自述『为一对一约束下的重复标注』，其 text/value 与主匹配"
            "条目互不相同（实测：『若从零开一个观察仓』vs『等两件事至少中一件再议』等）⇒ 判定由"
            "评分器一对一映射强加，非重复渲染；为满足评分侧约束删真条目属 83 号登记的反模式"
        ),
        "worksheet": {
            "path": str(WORKSHEET.relative_to(ROOT)),
            "sha256": f"sha256:{sha256(WORKSHEET)}",
            "candidate_count": len(rows),
            "judgement_tally": tally,
            "review_status": sorted({str(row["review_status"]) for row in rows}),
            "reviewers": sorted({str(row["reviewer"]) for row in rows}),
            "adjudicators": sorted({str(row["adjudicator"]) for row in rows}),
            "gold_fields_read": 0,
        },
        "freeze": {
            "path": str(FREEZE.relative_to(ROOT)),
            "manifest_sha256": f"sha256:{sha256(FREEZE / 'manifest.json')}",
        },
        "runs": ledger,
        "outputs": {
            str(path.relative_to(HERE)): hashlib.sha256(data.encode()).hexdigest()
            for path, data in outputs.items()
        },
    }
    outputs[HERE / "items-bridge-inputs-record.json"] = (
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    )

    if args.no_write:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        print("[no-write] nothing written.")
        return 0

    for path, data in outputs.items():
        assert_writable(path, reason="109 号 items 桥输入工件")
        if path.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite {path.name}; use --force")
        write_once(path, data, allow_overwrite=True)
    print(json.dumps(record["runs"], ensure_ascii=False, indent=2))
    print(f"wrote {len(outputs)} files under {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
