"""I4-4 生产重建：corpus schema（postgres@5432）播种 8 份 ReviewedDecision → build/check/publish → 活动集 8/8。

依据 i4-cutover-manifest.json change_list_migrate[1]（U 2026-09-23 停写窗口批准连续执行）。
路径沿用 I3-7 重验先例（audits/20260923-i37-final-reverify/i37_rebuild.py，U 2026-09-20
受支持重建路径），差异仅三点：

1. 目标 = 生产 postgres 库 corpus schema（已由 I4-7 migrate 建成，**不 teardown/apply**，
   前置断言 corpus_sources 为空表=全新 schema）；
2. r5g 生产放行 = 环境变量 ``CORPUS_TARGET_DB=postgres``（pg_target 唯一开关；在导入
   plugins 模块**之前**设置——``_SANDBOX_DB`` 在导入期解析）；
3. 归档根 = 本窗口审计目录 ``i44-archive/``（守卫 locked 配置禁写 data/；生产归档根
   归属属 C12 类裁决，随 I4-close 登记）。

其余逐字沿先例：dev-scope-manifest.json 八源（approved 6 + dev lane 2 supersede 链）、
admission-policy-dev.json、CORPUS_DEV_LANE=1、零模型（守卫阻断）、留出件零读取。
产物 write-once：i44-rebuild-report.json（含与 I3-7 基线的 build_id/单元/切块交叉核对）。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
GUARD = BASE / "guards/i4-window.json"
MANIFEST = BASE / "audits/20260920-i31-dev-lane/dev-scope-manifest.json"
DEV_POLICY = BASE / "audits/20260920-i31-dev-lane/admission-policy-dev.json"
ARCHIVE = HERE / "i44-archive"
I37_BASELINE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/rebuild-report.json"
SIGNED_DIR = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i42-topic-b-reingest"
OUT = HERE / "i44-rebuild-report.json"
OWNER = "i44-production-rebuild"
NOW = datetime(2026, 9, 23, 17, 0, tzinfo=UTC)  # = 2026-09-24T01:00+08:00（窗口内固定值）
REVIEWER = "U（I4 停写窗口 2026-09-24 具名批准连续执行；批准集 U 2026-09-15 逐字保留 + dev lane U 2026-09-20）"
TARGET_DB = "postgres"

assert ROOT == Path("/home/administrator/FrontierAgent")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cli_run(cli, argv: list[str]) -> dict:
    buf = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    text = buf.getvalue()
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError:
        payload = json.loads(text[text.find("{"):]) if "{" in text else {"raw": text[:2000]}
    return {"argv": argv, "exit_code": code, "seconds": round(time.perf_counter() - started, 2),
            "output": payload}


def _load_env(root: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in (root / ".env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    )


def _seed_decisions(store, sources, dev_policy, dev_by_path) -> list[dict]:
    from plugins.corpus.preparation.contract import (  # noqa: PLC0415
        MaterialType,
        ResearchDomain,
        ReviewDecision,
        ReviewedDecision,
        sha256_of_bytes,
    )

    seeded: list[dict] = []
    for entry in sources:
        path = str(entry["path"])
        source_id = sha256_of_bytes((ROOT / path).read_bytes())
        domain = ResearchDomain(str(entry["domain_hint"]))
        ids = list(entry["review_decision_ids"])
        if entry.get("provenance") == "approved_set":
            store.put_reviewed_decision(
                ReviewedDecision(
                    decision_id=ids[0],
                    source_id=source_id,
                    reviewer=REVIEWER,
                    reviewed_at=NOW,
                    decision=ReviewDecision.ADMITTED,
                    rationale="I4-4 生产重建重播种：U 2026-09-15 批准集（逐字保留）",
                    research_domain=domain,
                )
            )
            seeded.append({"path": path, "decisions": ids, "kind": "approved_set"})
        else:
            lane = dev_by_path[path]
            material = MaterialType(str(lane["material_type"]))
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
                    rationale=(
                        f"dev lane（{dev_policy['dev_lane']['lane_id']}）：{lane['reason']}"
                    ),
                    material_type=material,
                    research_domain=domain,
                    supersedes=ids[0],
                )
            )
            seeded.append({"path": path, "decisions": ids, "kind": "dev_lane",
                           "material_type": str(lane["material_type"])})
    return seeded


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"拒绝：write-once 报告已存在 {OUT}")

    env_cfg = _load_env(ROOT)
    cred = env_cfg["CORPUS_DSN"].split("://", 1)[1].rsplit("@", 1)[0]
    prod_dsn = f"postgresql://{cred}@127.0.0.1:5432/{TARGET_DB}"

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dev_policy = json.loads(DEV_POLICY.read_text(encoding="utf-8"))
    dev_by_path = {str(item["path"]): item for item in dev_policy["dev_lane"]["sources"]}
    sources = manifest["sources"]
    cutover = json.loads((BASE / "i4-cutover-manifest.json").read_text(encoding="utf-8"))

    # ── 守卫先装（任何业务 import 之前）；r5g 生产放行 env 必须在导入前设置 ──
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    os.environ["CORPUS_DEV_LANE"] = "1"
    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard as guard_module  # noqa: PLC0415

    guard_module.install(GUARD)
    from plugins.corpus import cli  # noqa: PLC0415
    from plugins.corpus.preparation.pg_target import resolve_target_db  # noqa: PLC0415
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    resolved = resolve_target_db()
    if resolved != TARGET_DB:
        raise SystemExit(f"拒绝：resolve_target_db()={resolved!r} ≠ postgres（r5g 环境未生效）")

    record: dict = {
        "artifact": "i44-production-rebuild",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "authority": {
            "cutover_manifest_sha256": digest(BASE / "i4-cutover-manifest.json"),
            "change_list_migrate_item": cutover["change_list_migrate"][1],
            "approval_window": cutover["approval"]["window"],
        },
        "code_version": {
            "freeze_chain_head": cutover["code_version_binding"]["freeze_chain_head"],
            "chain_head_sha256": cutover["code_version_binding"]["chain_head_sha256"],
        },
        "target": {"dsn": "postgresql://***@127.0.0.1:5432/postgres", "schema": "corpus"},
        "target_adapter": {
            "resolve_target_db": resolved,
            "env": "CORPUS_TARGET_DB=postgres（r5g 显式授权；CORPUS_DEV_LANE=1 dev lane 开关）",
        },
        "scope": {"manifest": str(MANIFEST.relative_to(ROOT)), "manifest_sha256": digest(MANIFEST),
                  "size": len(sources), "sources": [s["path"] for s in sources]},
        "guard": {"path": str(GUARD.relative_to(ROOT)), "sha256": digest(GUARD)},
        "archive_root": {"path": str(ARCHIVE.relative_to(ROOT)),
                         "note": "守卫 locked 配置禁写 data/；生产归档根归属属 C12 类裁决，随 I4-close 登记"},
    }

    # ── 前置断言：corpus schema 在位且全新（零源/零构建/零发布/零决定）──
    import psycopg  # noqa: PLC0415
    with psycopg.connect(prod_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(
            "SELECT (SELECT count(*) FROM corpus.corpus_sources) AS sources,"
            " (SELECT count(*) FROM corpus.corpus_builds) AS builds,"
            " (SELECT count(*) FROM corpus.corpus_review_decisions) AS decisions,"
            " (SELECT count(*) FROM corpus.corpus_publications) AS publications"
        )
        counts = dict(zip([d[0] for d in cur.description], cur.fetchone()))
    if counts["sources"] or counts["builds"] or counts["decisions"] or counts["publications"]:
        raise SystemExit(f"拒绝：corpus schema 非全新 {counts}（重演须先按 rollback 路径处理）")
    record["pre_state"] = counts

    # ── Step 1: 播种 8 份审查决定（6 approved + 2×2 dev lane 取代链）──
    store = PgStore(prod_dsn, sandbox_db=resolved)
    try:
        record["seeded_decisions"] = _seed_decisions(store, sources, dev_policy, dev_by_path)
    finally:
        store.close()

    # ── Step 2: build ──
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    build = cli_run(cli, ["build", "--manifest", str(MANIFEST), "--dsn", prod_dsn,
                          "--owner", OWNER, "--archive-root", str(ARCHIVE)])
    outcomes = {str(o.get("original_name")): o for o in (build["output"] or {}).get("outcomes") or []}
    record["build"] = {"exit_code": build["exit_code"], "seconds": build["seconds"],
                       "count": (build["output"] or {}).get("count"),
                       "errors": (build["output"] or {}).get("error")}

    # ── Step 3: check + publish 逐来源（阻断时按 I3-7 先例找已签署 gap-review）──
    baseline_rows = {r["original_name"]: r for r in json.loads(I37_BASELINE.read_text(encoding="utf-8"))["per_source"]}
    per_source = []
    for entry in sources:
        name = Path(str(entry["path"])).name
        outcome = outcomes.get(name) or {}
        fmt = Path(name).suffix.lower().lstrip(".")
        row = {"path": str(entry["path"]), "domain": str(entry["domain_hint"]), "format": fmt,
               "provenance": entry.get("provenance"), "original_name": name,
               "decision": outcome.get("decision"), "build_id": outcome.get("build_id"),
               "unit_count": outcome.get("unit_count"), "chunk_count": outcome.get("chunk_count")}
        if outcome.get("decision") == "in_scope" and outcome.get("build_id"):
            checked = cli_run(cli, ["check", "--build", str(outcome["build_id"]), "--dsn", prod_dsn])
            gaps = (checked["output"] or {}).get("gaps") or []
            row["check_exit"] = checked["exit_code"]
            row["publishable"] = (checked["output"] or {}).get("publishable")
            row["blocking_gaps"] = [
                {"key": g.get("key"), "code": g.get("code"), "status": g.get("status"),
                 "disposition": g.get("disposition"), "remedy": str(g.get("remedy"))[:100]}
                for g in gaps if str(g.get("disposition")) not in ("acknowledged", "noise")
            ]
            row["check_error"] = (checked["output"] or {}).get("error")
            if checked["exit_code"] == 0:
                published = cli_run(cli, ["publish", "--build", str(outcome["build_id"]),
                                          "--operator", OWNER, "--dsn", prod_dsn])
                row["publish"] = {"exit_code": published["exit_code"],
                                  "generation": (published["output"] or {}).get("generation"),
                                  "active_build_id": (published["output"] or {}).get("active_build_id")}
            else:
                row["publish"] = {"exit_code": checked["exit_code"], "blocked": True}
        # 与 I3-7 沙箱基线交叉核对（同冻结代码 ⇒ 确定性；差异即记录，不阻断）
        base = baseline_rows.get(name) or {}
        row["i37_baseline"] = {
            "build_id": base.get("build_id"),
            "build_id_match": (base.get("build_id") == row.get("build_id")),
            "unit_count": base.get("unit_count"),
            "chunk_count": base.get("chunk_count"),
            "units_match": (base.get("unit_count") == row.get("unit_count")),
            "chunks_match": (base.get("chunk_count") == row.get("chunk_count")),
        }
        per_source.append(row)

    record["gap_review_applied"] = []
    for row in per_source:
        bid = row.get("build_id")
        if not bid or (row.get("publish") or {}).get("exit_code") == 0:
            continue
        signed = SIGNED_DIR / f"signed-{bid[:16]}.json"
        if not signed.is_file():
            row["gap_review"] = {"error": f"missing signed record: {signed.name}"}
            continue
        applied = cli_run(cli, ["gap-review", "--build", str(bid), "--record", str(signed),
                                "--dsn", prod_dsn])
        row["gap_review"] = {"record": str(signed.relative_to(ROOT)), "record_sha256": digest(signed),
                             "exit_code": applied["exit_code"], "output": applied["output"]}
        record["gap_review_applied"].append(row["original_name"])
        if applied["exit_code"] == 0:
            rechecked = cli_run(cli, ["check", "--build", str(bid), "--dsn", prod_dsn])
            row["check_exit"] = rechecked["exit_code"]
            row["publishable"] = (rechecked["output"] or {}).get("publishable")
            row["blocking_gaps"] = [
                {"key": g.get("key"), "code": g.get("code"), "status": g.get("status"),
                 "disposition": g.get("disposition"), "remedy": str(g.get("remedy"))[:100]}
                for g in (rechecked["output"] or {}).get("gaps") or []
                if str(g.get("disposition")) not in ("acknowledged", "noise")
            ]
            if rechecked["exit_code"] == 0:
                published = cli_run(cli, ["publish", "--build", str(bid),
                                          "--operator", OWNER, "--dsn", prod_dsn])
                row["publish"] = {"exit_code": published["exit_code"],
                                  "generation": (published["output"] or {}).get("generation"),
                                  "active_build_id": (published["output"] or {}).get("active_build_id"),
                                  "after_gap_review": True}

    # ── Step 4: 读指针核验（活动集 8/8）──
    with PgStore(prod_dsn, sandbox_db=resolved) as store:
        for row in per_source:
            bid = row.get("build_id")
            b = store.get_build(bid) if bid else None
            if b is not None:
                row["parse_rev"] = b.parse_rev
                row["clean_rev"] = b.clean_rev
                row["chunk_rev"] = b.chunk_rev
                row["index_rev"] = b.index_rev
            pub = store.get_publication(b.source_id) if b is not None else None
            row["active"] = bool(pub and pub.active_build_id == bid)
            row["generation_now"] = pub.generation if pub else None

    record["per_source"] = per_source
    record["summary"] = {
        "sources": len(per_source),
        "built": sum(1 for r in per_source if r.get("build_id")),
        "published": sum(1 for r in per_source if (r.get("publish") or {}).get("exit_code") == 0),
        "blocked": sum(1 for r in per_source if (r.get("publish") or {}).get("blocked")),
        "active": sum(1 for r in per_source if r.get("active")),
        "index_revs": sorted({str(r.get("index_rev")) for r in per_source if r.get("index_rev")}),
        "all_new_build_active": all(r.get("active") for r in per_source if r.get("build_id")),
        "build_id_matches_i37_baseline": all(
            r["i37_baseline"]["build_id_match"] for r in per_source if r.get("build_id")
        ),
        "unit_chunk_counts_match_i37": all(
            r["i37_baseline"]["units_match"] and r["i37_baseline"]["chunks_match"]
            for r in per_source if r.get("build_id")
        ),
    }
    with psycopg.connect(prod_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(
            "SELECT (SELECT count(*) FROM corpus.corpus_sources) AS sources,"
            " (SELECT count(*) FROM corpus.corpus_review_decisions) AS decisions,"
            " (SELECT count(*) FROM corpus.corpus_builds) AS builds,"
            " (SELECT count(*) FROM corpus.corpus_chunks) AS chunks,"
            " (SELECT count(*) FROM corpus.corpus_units) AS units,"
            " (SELECT count(*) FROM corpus.corpus_publications) AS publications,"
            " (SELECT count(*) FROM corpus.corpus_publications WHERE active_build_id IS NOT NULL) AS active"
        )
        record["post_state"] = dict(zip([d[0] for d in cur.description], cur.fetchone()))

    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": record["summary"], "post_state": record["post_state"],
                      "build": record["build"]}, ensure_ascii=False, indent=2))
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
