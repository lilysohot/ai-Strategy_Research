"""I5-1 场景三：新规则 build（隔离库 i51_s3_newrule，运行时内存补丁模拟规则升级）。

U 2026-09-24 批准范围（r5n m8_kickoff）：全四场景 × 全部 8 个活动源。场景三验证链：

1. v1 基线：全新隔离库同清单 build+check+publish（4 直接 + 4 复用 I3-7 已签署
   gap-review）→ 8/8 活动于 generation 1，逐源 build_id 与生产 I4-4 基线相等。
2. 规则变更（模拟）：**不改冻结代码文件**——进程内补丁
   ``engine.PARSE_RULE_REV = "parse-3-i5sim"``（守卫 guards/i5-scenarios.json note
   已声明该模拟方式；engine.py 文件 sha256 前后相等作零修改证据），finally 恢复。
3. 同清单重跑：解析检查点校验命中 ``parse_rule_rev`` 不匹配 → reparse_reason=
   ``rule_or_source_mismatch`` → 全部 8 源真实重解析（reader spy 注入
   ``cli.execute_builds`` 计数 = 8）→ 每源得到**新 build_id**（parse_rev 进入
   build_id；8/8 含 MD）→ 检查点整体重写（parse_rule_rev/reparse_reason/updated_at）。
4. 版本语义：run2 build 与 v1 build 并存（v1 全部仍可 get_build）；4 直接源发布
   run2 → generation 1→2、活动指针切换；4 gap 源 run2 check 阻断（EXIT_GATE），
   活动指针保持 v1 build（generation 1）——发布面 fail-closed，新版本不强制上线。
5. 内容等值：run2 逐源 unit/chunk 计数与 v1 全等（解析规则变更不影响读取器产出；
   变化只体现在 build_id/版本翻新）。
6. 生产只读：前/后快照全等；库级计数 builds=16、units/chunks 翻倍、publications/active=8。

产物 write-once：i51-s3-newrule-report.json。
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import i51_common as common  # noqa: E402

OUT = HERE / "i51-s3-newrule-report.json"
DB = "i51_s3_newrule"
OWNER = "i51-s3-newrule"
NOW = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)
SIM_RULE = "parse-3-i5sim"
ORIG_RULE = "parse-2"

ENGINE_PY = common.ROOT / "plugins/corpus/preparation/engine.py"


def checkpoints_snapshot(dsn: str) -> dict[str, dict]:
    """逐源解析检查点投影（corpus.corpus_source_checkpoints；checkpoint 为 jsonb）。"""
    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT source_id, checkpoint->>'parse_rule_rev', checkpoint->>'reparse_reason',"
            " checkpoint->>'extractor_rev', updated_at"
            " FROM corpus.corpus_source_checkpoints WHERE stage = 'parse' ORDER BY source_id"
        )
        return {
            r[0]: {"parse_rule_rev": r[1], "reparse_reason": r[2], "extractor_rev": r[3],
                   "updated_at": r[4].isoformat()}
            for r in cur.fetchall()
        }


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"拒绝：write-once 报告已存在 {OUT}")

    creds = common.load_env_credentials()
    pdsn = common.prod_dsn(creds)
    prod_pre = common.prod_readonly_snapshot(pdsn)

    cli, resolved = common.install_guard(DB)
    idsn = common.iso_dsn(creds, DB)

    manifest = common.MANIFEST
    dev_policy = json.loads(common.DEV_POLICY.read_text(encoding="utf-8"))
    dev_by_path = {str(item["path"]): item for item in dev_policy["dev_lane"]["sources"]}
    sources = json.loads(manifest.read_text(encoding="utf-8"))["sources"]
    i44 = json.loads(common.I44_REPORT.read_text(encoding="utf-8"))
    baseline_rows = {r["original_name"]: r for r in i44["per_source"]}

    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    engine_sha_pre = common.digest(ENGINE_PY)
    record: dict = {
        "artifact": "i51-s3-newrule",
        "scenario": "新规则 build（运行时内存补丁模拟 PARSE_RULE_REV 升级；冻结文件零修改）",
        "authority": {"guard": str(common.GUARD.relative_to(common.ROOT)),
                      "guard_sha256": common.digest(common.GUARD),
                      "manifest_sha256": common.digest(manifest),
                      "scope": "U 2026-09-24 批准：全四场景×全部 8 个活动源（r5n m8_kickoff）"},
        "target": {"dsn": f"postgresql://***@{common.ISO_HOST}:{common.ISO_PORT}/{DB}",
                   "resolve_target_db": resolved},
        "prod_pre": prod_pre,
        "prod_pre_counts_match_i44": prod_pre["counts"] == i44["post_state"],
    }

    # ── Step 1: 播种 8 份决定（与生产 I4-4 同决定链同 id）──
    store = PgStore(idsn, sandbox_db=resolved)
    try:
        record["seeded_decisions"] = common.seed_decisions(
            store, sources, dev_by_path, creds,
            decision_prefix=None, now=NOW,
            rationale_tag="I5-1 场景三重播种（隔离库；与生产 I4-4 同决定链同 id）")
    finally:
        store.close()

    # ── Step 2: v1 build + check + publish（4 直接 + 4 signed gap-review）──
    v1_report, v1_rows = common.build_check_publish(
        cli, idsn, manifest, HERE / "s3-archive", OWNER, baseline_rows, gap_review=True)
    record["v1_run"] = v1_report

    # ── Step 3: v1 状态与检查点快照（补丁前）──
    store = PgStore(idsn, sandbox_db=resolved)
    try:
        for row in v1_rows:
            b = store.get_build(row["build_id"]) if row.get("build_id") else None
            pub = store.get_publication(b.source_id) if b is not None else None
            row["kind"] = ("gap_source"
                           if (row.get("publish") or {}).get("after_gap_review") else "direct")
            row["generation"] = pub.generation if pub else None
            row["active"] = bool(pub and pub.active_build_id == row.get("build_id"))
    finally:
        store.close()
    ckpt_pre = checkpoints_snapshot(idsn)
    record["v1_state"] = {
        "built": sum(1 for r in v1_rows if r.get("build_id")),
        "published": sum(1 for r in v1_rows if (r.get("publish") or {}).get("exit_code") == 0),
        "active": sum(1 for r in v1_rows if r.get("active")),
        "build_id_match_i44": all(r["i44_baseline"]["build_id_match"]
                                  for r in v1_rows if r.get("build_id")),
        "checkpoints": ckpt_pre,
    }

    # ── Step 4: 规则补丁 + reader spy → 同清单重跑 ──
    import plugins.corpus.preparation.engine as engine_mod  # noqa: PLC0415
    from plugins.corpus.preparation.readers import read_document as real_reader  # noqa: PLC0415

    spy_calls: list[str] = []

    def _spy_reader(path: Path):
        spy_calls.append(Path(str(path)).name)
        return real_reader(Path(path))

    orig_exec = cli.execute_builds

    def _exec_spy(*args, **kwargs):
        kwargs["reader"] = _spy_reader
        return orig_exec(*args, **kwargs)

    if engine_mod.PARSE_RULE_REV != ORIG_RULE:
        raise SystemExit(f"拒绝：engine 初始 PARSE_RULE_REV={engine_mod.PARSE_RULE_REV!r} 非预期")
    if orig_exec is not engine_mod.execute_builds:
        # cli 模块命名空间里的 execute_builds 必须指向 engine 同一函数（运行时可包装前提）。
        raise SystemExit("拒绝：cli.execute_builds 与 engine.execute_builds 不同一")
    try:
        engine_mod.PARSE_RULE_REV = SIM_RULE
        cli.execute_builds = _exec_spy
        run2 = common.cli_run(cli, ["build", "--manifest", str(manifest), "--dsn", idsn,
                                    "--owner", OWNER, "--archive-root", str(HERE / "s3-archive")])
    finally:
        cli.execute_builds = orig_exec
        engine_mod.PARSE_RULE_REV = ORIG_RULE
    record["simulation"] = {
        "mechanism": "in-process 模块属性补丁（不改冻结文件；守卫 i5-scenarios note 已声明）",
        "patched": "plugins.corpus.preparation.engine.PARSE_RULE_REV",
        "simulated_value": SIM_RULE,
        "original_value": ORIG_RULE,
        "restored": engine_mod.PARSE_RULE_REV == ORIG_RULE and cli.execute_builds is orig_exec,
        "engine_file_sha256_pre": engine_sha_pre,
        "engine_file_sha256_post": common.digest(ENGINE_PY),
        "engine_file_unchanged": common.digest(ENGINE_PY) == engine_sha_pre,
        "reader_spy_calls": len(spy_calls),
        "reader_spy_paths": sorted(spy_calls),
    }
    record["run2_build"] = {"exit_code": run2["exit_code"], "seconds": run2["seconds"]}

    # ── Step 5: run2 逐源断言（新 build_id / 内容等值）+ check + publish（无 gap-review）──
    run2_out = {str(o.get("original_name")): o
                for o in (run2["output"] or {}).get("outcomes") or []}
    run2_rows: list[dict] = []
    for v1row in v1_rows:
        name = v1row["original_name"]
        o = run2_out.get(name) or {}
        row: dict = {
            "original_name": name,
            "kind": v1row["kind"],
            "v1_build_id": v1row.get("build_id"),
            "run2_build_id": o.get("build_id"),
            "build_id_changed": (o.get("build_id") != v1row.get("build_id"))
            if o.get("build_id") else None,
            "units_same": o.get("unit_count") == v1row.get("unit_count"),
            "chunks_same": o.get("chunk_count") == v1row.get("chunk_count"),
            "unit_count": o.get("unit_count"),
            "chunk_count": o.get("chunk_count"),
            "source_reused": o.get("source_reused"),
            "archive_reused": o.get("archive_reused"),
        }
        if o.get("build_id"):
            checked = common.cli_run(cli, ["check", "--build", str(o["build_id"]), "--dsn", idsn])
            row["check_exit"] = checked["exit_code"]
            row["publishable"] = (checked["output"] or {}).get("publishable")
            row["blocking_gaps"] = [
                {"code": g.get("code"), "status": g.get("status")}
                for g in (checked["output"] or {}).get("gaps") or []
                if str(g.get("disposition")) not in ("acknowledged", "noise")
            ]
            if checked["exit_code"] == 0:
                published = common.cli_run(cli, ["publish", "--build", str(o["build_id"]),
                                                 "--operator", OWNER, "--dsn", idsn])
                row["publish"] = {"exit_code": published["exit_code"],
                                  "generation": (published["output"] or {}).get("generation"),
                                  "active_build_id": (published["output"] or {}).get("active_build_id")}
            else:
                row["publish"] = {"exit_code": checked["exit_code"], "blocked": True}
        run2_rows.append(row)
    record["run2_check_publish"] = {"per_source": run2_rows}

    # ── Step 6: 检查点重写证据 + 版本语义（v1 保留 / 活动指针）──
    ckpt_post = checkpoints_snapshot(idsn)
    sid_by_name = {r["original_name"]: r.get("source_id") for r in v1_rows}
    ckpt_rows = []
    for row in run2_rows:
        pre = ckpt_pre.get(sid_by_name[row["original_name"]] or "", {})
        post = ckpt_post.get(sid_by_name[row["original_name"]] or "", {})
        ckpt_rows.append({
            "original_name": row["original_name"],
            "pre_parse_rule_rev": pre.get("parse_rule_rev"),
            "post_parse_rule_rev": post.get("parse_rule_rev"),
            "post_reparse_reason": post.get("reparse_reason"),
            "post_extractor_rev": post.get("extractor_rev"),
            "updated_at_changed": pre.get("updated_at") != post.get("updated_at"),
        })
    record["checkpoints_after_run2"] = ckpt_rows

    store = PgStore(idsn, sandbox_db=resolved)
    try:
        for row in run2_rows:
            b2 = store.get_build(row["run2_build_id"]) if row.get("run2_build_id") else None
            b1 = store.get_build(row["v1_build_id"]) if row.get("v1_build_id") else None
            ref = b2 or b1
            pub = store.get_publication(ref.source_id) if ref is not None else None
            row["v1_build_retained"] = b1 is not None
            row["active_build_id"] = pub.active_build_id if pub else None
            row["generation"] = pub.generation if pub else None
            if row["kind"] == "direct":
                row["active_switched_to_run2_gen2"] = bool(
                    pub and pub.active_build_id == row.get("run2_build_id")
                    and pub.generation == 2)
            else:
                row["v1_still_active_gen1"] = bool(
                    pub and pub.active_build_id == row.get("v1_build_id")
                    and pub.generation == 1)
    finally:
        store.close()

    direct = [r for r in run2_rows if r["kind"] == "direct"]
    gap = [r for r in run2_rows if r["kind"] == "gap_source"]
    counts = common.iso_counts(idsn)
    record["iso_counts_after_run2"] = counts

    # ── Step 7: 汇总 + 生产后置快照 ──
    record["summary"] = {
        "v1_built": record["v1_state"]["built"],
        "v1_published": record["v1_state"]["published"],
        "v1_active": record["v1_state"]["active"],
        "v1_build_id_match_i44": record["v1_state"]["build_id_match_i44"],
        "run2_exit_code": run2["exit_code"],
        "run2_all_in_scope": all(r.get("run2_build_id") for r in run2_rows),
        "run2_build_id_all_changed": all(r["build_id_changed"] for r in run2_rows),
        "run2_content_identical": all(r["units_same"] and r["chunks_same"] for r in run2_rows),
        "run2_source_reused": all(r["source_reused"] and r["archive_reused"] for r in run2_rows),
        "reader_spy_calls": len(spy_calls),
        "checkpoints_all_rule_mismatch": all(
            c["post_parse_rule_rev"] == SIM_RULE
            and c["post_reparse_reason"] == "rule_or_source_mismatch"
            and c["updated_at_changed"] for c in ckpt_rows),
        "direct_sources_switched": [r["original_name"] for r in direct
                                    if r.get("active_switched_to_run2_gen2")],
        "direct_sources_total": len(direct),
        "gap_sources_kept_v1": [r["original_name"] for r in gap
                                if r.get("v1_still_active_gen1")],
        "gap_sources_total": len(gap),
        "v1_builds_all_retained": all(r["v1_build_retained"] for r in run2_rows),
        "simulation_restored": record["simulation"]["restored"]
        and record["simulation"]["engine_file_unchanged"],
        "counts_after_run2": {
            "builds_doubled": counts.get("builds") == 16,
            "units_doubled": counts.get("units") == 2 * 3887,
            "chunks_doubled": counts.get("chunks") == 2 * 834,
            "publications_still_8": counts.get("publications") == 8,
            "active_still_8": counts.get("active") == 8,
        },
    }
    record["prod_post"] = common.prod_readonly_snapshot(pdsn)
    record["prod_unchanged"] = record["prod_post"] == prod_pre

    gate = (
        record["summary"]["v1_built"] == 8 and record["summary"]["v1_published"] == 8
        and record["summary"]["v1_active"] == 8 and record["summary"]["v1_build_id_match_i44"]
        and run2["exit_code"] == 0
        and record["summary"]["run2_all_in_scope"]
        and record["summary"]["run2_build_id_all_changed"]
        and record["summary"]["run2_content_identical"]
        and record["summary"]["run2_source_reused"]
        and record["summary"]["reader_spy_calls"] == 8
        and record["summary"]["checkpoints_all_rule_mismatch"]
        and len(record["summary"]["direct_sources_switched"]) == 4
        and len(record["summary"]["gap_sources_kept_v1"]) == 4
        and record["summary"]["v1_builds_all_retained"]
        and record["summary"]["simulation_restored"]
        and all(record["summary"]["counts_after_run2"].values())
        and record["prod_unchanged"] and record["prod_pre_counts_match_i44"]
    )
    record["gate_passed"] = gate
    record["gate_note"] = ("通过：规则升级 → 检查点 rule_or_source_mismatch 全量重解析（spy=8）"
                           "→ 8/8 新 build_id（内容全等）；4 直接源 gen2 切换、4 gap 源保持 v1 活动；"
                           "v1 版本并存；冻结文件零修改；生产零触碰" if gate else "未通过")

    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate_passed": gate, "summary": record["summary"]},
                     ensure_ascii=False, indent=2))
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "…")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
