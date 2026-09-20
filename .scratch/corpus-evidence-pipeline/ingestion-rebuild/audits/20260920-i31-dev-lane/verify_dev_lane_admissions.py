"""核验 dev lane 落库事实（只读沙箱）：材料类型如实 + policy_rev + dev lane 证据标记。

为什么单独一件证据：§12.1 格式门只要求「有真实已用样本」，而 U 2026-09-20 裁决额外要求
`material_type` **如实**（不得伪写为 research_report）且 in_scope 只在 dev 政策下成立。
本脚本直接读 `corpus.corpus_admissions` / `corpus_publications` 取证，不重算、不写入。

用法::

    uv run python .scratch/.../audits/20260920-i31-dev-lane/verify_dev_lane_admissions.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
MANIFEST = HERE / "dev-scope-manifest.json"
DEV_POLICY = HERE / "admission-policy-dev.json"
OUT = HERE / "dev-lane-admission-verification.json"
SANDBOX_DB = "i2_sandbox_corpus"

SQL = """
SELECT s.source_id,
       a.decision_id,
       a.decision,
       a.material_type,
       a.research_domain,
       a.policy_rev,
       a.review_ref,
       a.evidence_refs,
       p.active_build_id,
       p.generation
FROM corpus.corpus_sources s
LEFT JOIN corpus.corpus_admissions a ON a.decision_id = s.current_decision_id
LEFT JOIN corpus.corpus_publications p ON p.source_id = s.source_id
WHERE s.source_id = %(source_id)s
"""


def main() -> int:
    env = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    )
    dsn = (
        f"postgresql://{env['CORPUS_DSN'].split('://', 1)[1].rsplit('@', 1)[0]}"
        "@127.0.0.1:543/i2_sandbox_corpus"
    )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dev_policy = json.loads(DEV_POLICY.read_text(encoding="utf-8"))
    lane = dev_policy["dev_lane"]
    dev_sources = [s for s in manifest["sources"] if s.get("provenance") == "dev_lane"]
    declared = {str(item["source_id"]): item for item in lane["sources"]}

    import psycopg  # noqa: PLC0415

    rows = []
    failures: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        for item in dev_sources:
            source_id = next(k for k, v in declared.items() if v["path"] == item["path"])
            cur.execute(SQL, {"source_id": source_id})
            row = cur.fetchone()
            if row is None:
                failures.append(f"{item['path']}: source 未入库")
                continue
            declared_item = declared[source_id]
            entry = {
                "path": item["path"],
                "source_id": source_id,
                "decision": row[2],
                "material_type": row[3],
                "research_domain": row[4],
                "policy_rev": row[5],
                "review_ref": row[6],
                "evidence_refs": list(row[7] or []),
                "active_build_id": row[8],
                "generation": row[9],
                "declared_material_type": declared_item["material_type"],
                "declared_i0a2_decision": declared_item["i0a2_decision"],
            }
            # 断言：in_scope ∧ 材料类型如实 ∧ dev 政策 ∧ 有发布 ∧ 材料类型 ≠ research_report
            if row[2] != "in_scope":
                failures.append(f"{item['path']}: decision={row[2]}（期望 in_scope）")
            if row[3] != declared_item["material_type"]:
                failures.append(
                    f"{item['path']}: material_type={row[3]} 与声明 {declared_item['material_type']} 不符"
                )
            if row[3] == "research_report":
                failures.append(f"{item['path']}: material_type 被伪写为 research_report")
            if row[5] != dev_policy["policy_rev"]:
                failures.append(f"{item['path']}: policy_rev={row[5]} 非 dev 政策")
            if row[8] is None:
                failures.append(f"{item['path']}: 无活动 build（未发布）")
            if not any(str(e).startswith(f"dev_lane={lane['lane_id']}") for e in (row[7] or [])):
                failures.append(f"{item['path']}: evidence_refs 缺 dev_lane 标记")
            rows.append(entry)

    report = {
        "artifact": "dev-lane-admission-verification",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "sandbox": f"postgresql://***@127.0.0.1:543/{SANDBOX_DB}",
        "lane_id": lane["lane_id"],
        "dev_policy_rev": dev_policy["policy_rev"],
        "rows": rows,
        "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
        "note": (
            "本核验只证明 dev lane 在隔离沙箱内的落库事实（材料类型如实 + dev 政策 + 已发布）。"
            "生产判定不变由两处独立证据承担：① tests/test_corpus_preparation_admission.py 的 dev lane 族"
            "（关闭 dev lane / v1 政策 / 未列入来源均拒绝）；② preflight fail-closed 反例。"
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "rows": [
        {k: r[k] for k in ("path", "decision", "material_type", "policy_rev", "generation")}
        for r in rows], "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
