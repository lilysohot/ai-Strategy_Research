"""登记 8 份来源的人审决定到沙箱库 i2_sandbox_corpus（U 2026-09-20 裁决）。

与 run_i3_1_dev_lane.py 的 seeding 口径逐字一致：
- approved_set（6 份）：单条 ADMITTED，reviewer=REVIEWER，NOW；
- dev_lane（2 份）：两条完整取代链
  i0a2-adjudicated-20260915（excluded_from_active）→ dev admitted（supersedes 指向前者）。
decision_id 与 dev-scope-manifest.json 的 review_decision_ids 完全一致。

只做登记，不 build / publish / commit/ teardown / gap-review --record。
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
MANIFEST = HERE / "dev-scope-manifest.json"
DEV_POLICY = HERE / "admission-policy-dev.json"
SANDBOX_DB = "i2_sandbox_corpus"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
REVIEWER = "U（2026-09-20 会话裁决：新建 dev lane；material_type 如实）"


def main() -> int:
    import json

    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation.contract import (  # noqa: PLC0415
        MaterialType,
        ResearchDomain,
        ReviewDecision,
        ReviewedDecision,
        sha256_of_bytes,
    )
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    dsn = (
        "postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus"
    )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dev_policy = json.loads(DEV_POLICY.read_text(encoding="utf-8"))
    dev_by_path = {str(item["path"]): item for item in dev_policy["dev_lane"]["sources"]}
    sources = manifest["sources"]
    lane_id = dev_policy["dev_lane"]["lane_id"]

    store = PgStore(dsn, sandbox_db=SANDBOX_DB)
    rows: list[dict] = []
    try:
        for entry in sources:
            path = str(entry["path"])
            source_id = sha256_of_bytes((ROOT / path).read_bytes())
            domain = ResearchDomain(str(entry["domain_hint"]))
            ids = list(entry["review_decision_ids"])
            if entry.get("provenance") == "approved_set":
                assert len(ids) == 1, path
                store.put_reviewed_decision(
                    ReviewedDecision(
                        decision_id=ids[0],
                        source_id=source_id,
                        reviewer=REVIEWER,
                        reviewed_at=NOW,
                        decision=ReviewDecision.ADMITTED,
                        rationale="I3-1 第二轮：U 2026-09-15 批准集（逐字保留）",
                        research_domain=domain,
                    )
                )
                rows.append({"path": path, "kind": "approved_set", "decisions": ids})
            else:
                lane = dev_by_path[path]
                material = MaterialType(str(lane["material_type"]))
                assert len(ids) == 2, path
                store.put_reviewed_decision(
                    ReviewedDecision(
                        decision_id=ids[0],
                        source_id=source_id,
                        reviewer="U（i0a2-adjudicated-20260915.json）",
                        reviewed_at=datetime(2026, 9, 15, 8, 20, 52, tzinfo=UTC),
                        decision=ReviewDecision(lane["i0a2_decision"]),
                        rationale=str(lane["i0a2_note"]),
                        material_type=material,
                    )
                )
                store.put_reviewed_decision(
                    ReviewedDecision(
                        decision_id=ids[1],
                        source_id=source_id,
                        reviewer=REVIEWER,
                        reviewed_at=NOW,
                        decision=ReviewDecision.ADMITTED,
                        rationale=f"dev lane（{lane_id}）：{lane['reason']}",
                        material_type=material,
                        research_domain=domain,
                        supersedes=ids[0],
                    )
                )
                rows.append({
                    "path": path, "kind": "dev_lane", "decisions": ids,
                    "material_type": str(lane["material_type"]),
                })
    finally:
        store.close()
    print(json.dumps({"seeded_decisions": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())