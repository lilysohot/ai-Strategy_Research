"""I5-1 场景四：复用解析重建索引（隔离库 i51_s4_idxreb，运行时内存补丁模拟 index_rev 升级）。

U 2026-09-24 批准范围（r5n m8_kickoff）：全四场景 × 全部 8 个活动源。场景四验证链：

1. v1 基线：全新隔离库同清单 build+check+publish（4 直接 + 4 复用 I3-7 已签署
   gap-review）→ 8/8 活动于 generation 1，逐源 build_id 与生产 I4-4 基线相等。
2. 索引版本变更（模拟）：**不改冻结代码文件**——进程内补丁
   ``engine.INDEX_REV_V3 = "index-5-i5sim"``（守卫 guards/i5-scenarios.json note 已
   声明；engine.py 文件 sha256 前后相等作零修改证据），finally 恢复。
3. 同清单重跑：解析检查点**有效复用**——reader spy 注入 ``cli.execute_builds`` 计数
   = 0（read_document 零调用）、检查点行 updated_at/parse_rule_rev/reparse_reason
   原样不动；clean/chunk 重算，index_rev 进入 build_id → 8/8 得到**新 build_id**
   （即「复用解析、重建索引」语义：新 build 重新生成 chunks 行，search_tsv 为
   GENERATED 列随新行重建，逐源 search_text 多重集与 v1 全等）。
4. parse_rev 归因：run2 build 的 parse_rev 与 v1 相等**仅** MD 源（静态读取器 rev；
   故 MD 的 build_id 变化可单独归因于 index_rev）；其余 7 源 parse_rev 不等——
   发现 F1（检查点复用回填裸 rev）在场景四同样可见，如实登记不重复定性。
   run2 全部 8 源 parse_rev == expected_parse_rev(source)（复用判定侧同一公式）。
5. 版本语义：v1 build 全部保留；4 直接源发布 run2 → generation 2、活动指针切换；
   4 gap 源 run2 check 阻断（EXIT_GATE），活动指针保持 v1（generation 1）。
6. 生产只读：前/后快照全等；库级计数 builds=16、units/chunks 翻倍、
   publications/active=8。

产物 write-once：i51-s4-idxreb-report.json。
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

OUT = HERE / "i51-s4-idxreb-report.json"
DB = "i51_s4_idxreb"
OWNER = "i51-s4-idxreb"
NOW = datetime(2026, 9, 24, 4, 0, tzinfo=UTC)
SIM_INDEX = "index-5-i5sim"
ORIG_INDEX = "index-4-zhcfg-2"

ENGINE_PY = common.ROOT / "plugins/corpus/preparation/engine.py"


def checkpoints_snapshot(dsn: str) -> dict[str, dict]:
    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT source_id, checkpoint->>'parse_rule_rev', checkpoint->>'reparse_reason',"
            " updated_at FROM corpus.corpus_source_checkpoints WHERE stage = 'parse'"
            " ORDER BY source_id"
        )
        return {r[0]: {"parse_rule_rev": r[1], "reparse_reason": r[2],
                       "updated_at": r[3].isoformat()} for r in cur.fetchall()}


def chunk_texts(dsn: str, build_id: str) -> list[str]:
    """指定 build 的逐块 search_text（按 chunk_id 排序）与 tsv 覆盖计数。"""
    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT search_text, (search_tsv IS NOT NULL) FROM corpus.corpus_chunks"
            " WHERE build_id = %s ORDER BY chunk_id", (build_id,))
        rows = cur.fetchall()
    return [r[0] for r in rows], sum(1 for r in rows if r[1])


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
        "artifact": "i51-s4-idxreb",
        "scenario": "复用解析重建索引（运行时内存补丁模拟 INDEX_REV_V3 升级；冻结文件零修改）",
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
            rationale_tag="I5-1 场景四重播种（隔离库；与生产 I4-4 同决定链同 id）")
    finally:
        store.close()

    # ── Step 2: v1 build + check + publish（4 直接 + 4 signed gap-review）──
    v1_report, v1_rows = common.build_check_publish(
        cli, idsn, manifest, HERE / "s4-archive", OWNER, baseline_rows, gap_review=True)
    record["v1_run"] = v1_report

    # ── Step 3: v1 状态 + 检查点快照（补丁前）──
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

    # ── Step 4: index_rev 补丁 + reader spy → 同清单重跑（期待解析零重算）──
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

    if engine_mod.INDEX_REV_V3 != ORIG_INDEX:
        raise SystemExit(f"拒绝：engine 初始 INDEX_REV_V3={engine_mod.INDEX_REV_V3!r} 非预期")
    if orig_exec is not engine_mod.execute_builds:
        raise SystemExit("拒绝：cli.execute_builds 与 engine.execute_builds 不同一")
    try:
        engine_mod.INDEX_REV_V3 = SIM_INDEX
        cli.execute_builds = _exec_spy
        run2 = common.cli_run(cli, ["build", "--manifest", str(manifest), "--dsn", idsn,
                                    "--owner", OWNER, "--archive-root", str(HERE / "s4-archive")])
    finally:
        cli.execute_builds = orig_exec
        engine_mod.INDEX_REV_V3 = ORIG_INDEX
    record["simulation"] = {
        "mechanism": "in-process 模块属性补丁（不改冻结文件；守卫 i5-scenarios note 已声明）",
        "patched": "plugins.corpus.preparation.engine.INDEX_REV_V3",
        "simulated_value": SIM_INDEX,
        "original_value": ORIG_INDEX,
        "restored": engine_mod.INDEX_REV_V3 == ORIG_INDEX and cli.execute_builds is orig_exec,
        "engine_file_sha256_pre": engine_sha_pre,
        "engine_file_sha256_post": common.digest(ENGINE_PY),
        "engine_file_unchanged": common.digest(ENGINE_PY) == engine_sha_pre,
        "reader_spy_calls": len(spy_calls),
        "reader_spy_paths": sorted(spy_calls),
    }
    record["run2_build"] = {"exit_code": run2["exit_code"], "seconds": run2["seconds"]}

    # ── Step 5: run2 逐源：新 build_id / revs 归因 / 内容与索引文本等值 ──
    run2_out = {str(o.get("original_name")): o
                for o in (run2["output"] or {}).get("outcomes") or []}
    run2_rows: list[dict] = []
    store = PgStore(idsn, sandbox_db=resolved)
    try:
        for v1row in v1_rows:
            name = v1row["original_name"]
            o = run2_out.get(name) or {}
            row: dict = {
                "original_name": name,
                "kind": v1row["kind"],
                "source_id": v1row.get("source_id"),
                "v1_build_id": v1row.get("build_id"),
                "run2_build_id": o.get("build_id"),
                "build_id_changed": (o.get("build_id") != v1row.get("build_id"))
                if o.get("build_id") else None,
                "units_same": o.get("unit_count") == v1row.get("unit_count"),
                "chunks_same": o.get("chunk_count") == v1row.get("chunk_count"),
                "source_reused": o.get("source_reused"),
                "archive_reused": o.get("archive_reused"),
            }
            if o.get("build_id") and v1row.get("build_id"):
                b1 = store.get_build(v1row["build_id"])
                b2 = store.get_build(o["build_id"])
                src = store.get_source(b1.source_id)
                from plugins.corpus.preparation.engine import expected_parse_rev  # noqa: PLC0415
                row["revs"] = {
                    "v1_parse_rev": b1.parse_rev,
                    "run2_parse_rev": b2.parse_rev,
                    "parse_rev_same": b1.parse_rev == b2.parse_rev,
                    "v1_index_rev": b1.index_rev,
                    "run2_index_rev": b2.index_rev,
                    "run2_parse_rev_matches_expected_formula": b2.parse_rev
                    == expected_parse_rev(src),
                }
            run2_rows.append(row)
    finally:
        store.close()
    for row in run2_rows:
        if row.get("run2_build_id") and row.get("v1_build_id"):
            v1_texts, v1_tsv = chunk_texts(idsn, row["v1_build_id"])
            r2_texts, r2_tsv = chunk_texts(idsn, row["run2_build_id"])
            row["index_evidence"] = {
                "v1_chunks": len(v1_texts), "run2_chunks": len(r2_texts),
                "search_text_multiset_equal": sorted(v1_texts) == sorted(r2_texts),
                "v1_tsv_nonnull": v1_tsv, "run2_tsv_nonnull": r2_tsv,
            }
    record["run2_build_revs"] = {"per_source": run2_rows}

    # ── Step 6: run2 check + publish（无 gap-review）+ 检查点未动证据 ──
    for row in run2_rows:
        if not row.get("run2_build_id"):
            continue
        checked = common.cli_run(cli, ["check", "--build", row["run2_build_id"], "--dsn", idsn])
        row["check_exit"] = checked["exit_code"]
        row["publishable"] = (checked["output"] or {}).get("publishable")
        row["blocking_gaps"] = [
            {"code": g.get("code"), "status": g.get("status")}
            for g in (checked["output"] or {}).get("gaps") or []
            if str(g.get("disposition")) not in ("acknowledged", "noise")
        ]
        if checked["exit_code"] == 0:
            published = common.cli_run(cli, ["publish", "--build", row["run2_build_id"],
                                             "--operator", OWNER, "--dsn", idsn])
            row["publish"] = {"exit_code": published["exit_code"],
                              "generation": (published["output"] or {}).get("generation"),
                              "active_build_id": (published["output"] or {}).get("active_build_id")}
        else:
            row["publish"] = {"exit_code": checked["exit_code"], "blocked": True}

    ckpt_post = checkpoints_snapshot(idsn)
    ckpt_rows = [{
        "original_name": row["original_name"],
        "pre_parse_rule_rev": ckpt_pre.get(row.get("source_id") or "", {}).get("parse_rule_rev"),
        "post_parse_rule_rev": ckpt_post.get(row.get("source_id") or "", {}).get("parse_rule_rev"),
        "pre_reparse_reason": ckpt_pre.get(row.get("source_id") or "", {}).get("reparse_reason"),
        "post_reparse_reason": ckpt_post.get(row.get("source_id") or "", {}).get("reparse_reason"),
        "updated_at_unchanged": (ckpt_pre.get(row.get("source_id") or {}, {}).get("updated_at")
                                 == ckpt_post.get(row.get("source_id") or {}, {}).get("updated_at")),
    } for row in run2_rows]
    record["checkpoints_after_run2"] = ckpt_rows

    store = PgStore(idsn, sandbox_db=resolved)
    try:
        for row in run2_rows:
            b1 = store.get_build(row["v1_build_id"]) if row.get("v1_build_id") else None
            b2 = store.get_build(row["run2_build_id"]) if row.get("run2_build_id") else None
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
    md_rows = [r for r in run2_rows if r["original_name"].lower().endswith(".md")]
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
        "checkpoints_all_untouched": all(
            c["updated_at_unchanged"] and c["post_parse_rule_rev"] == "parse-2"
            and c["post_reparse_reason"] == "checkpoint_absent" for c in ckpt_rows),
        "index_rev_all_simulated": all(
            (r.get("revs") or {}).get("run2_index_rev") == SIM_INDEX
            and (r.get("revs") or {}).get("v1_index_rev") == ORIG_INDEX for r in run2_rows),
        "search_text_multiset_all_equal": all(
            (r.get("index_evidence") or {}).get("search_text_multiset_equal")
            and (r.get("index_evidence") or {}).get("run2_tsv_nonnull")
            == (r.get("index_evidence") or {}).get("v1_chunks") for r in run2_rows),
        "parse_rev_same_only_md": (
            [r["original_name"] for r in run2_rows
             if (r.get("revs") or {}).get("parse_rev_same")] == [r["original_name"] for r in md_rows]
            and len(md_rows) == 1),
        "run2_parse_rev_matches_expected_formula": all(
            (r.get("revs") or {}).get("run2_parse_rev_matches_expected_formula")
            for r in run2_rows),
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
        and record["summary"]["reader_spy_calls"] == 0
        and record["summary"]["checkpoints_all_untouched"]
        and record["summary"]["index_rev_all_simulated"]
        and record["summary"]["search_text_multiset_all_equal"]
        and record["summary"]["parse_rev_same_only_md"]
        and record["summary"]["run2_parse_rev_matches_expected_formula"]
        and len(record["summary"]["direct_sources_switched"]) == 4
        and len(record["summary"]["gap_sources_kept_v1"]) == 4
        and record["summary"]["v1_builds_all_retained"]
        and record["summary"]["simulation_restored"]
        and all(record["summary"]["counts_after_run2"].values())
        and record["prod_unchanged"] and record["prod_pre_counts_match_i44"]
    )
    record["gate_passed"] = gate
    record["gate_note"] = ("通过：index_rev 升级 → 解析检查点全程复用（spy=0、检查点未动）→ "
                           "8/8 新 build_id 重建索引（search_text 多重集与 v1 全等、tsv 全覆盖）；"
                           "MD 源 parse_rev 不变（build_id 变化单因 index_rev），7 动态 rev 源"
                           " parse_rev 翻转为 F1 既有行为；4 直接源 gen2 切换、4 gap 源保持 v1 活动；"
                           "冻结文件零修改；生产零触碰" if gate else "未通过")

    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate_passed": gate, "summary": record["summary"]},
                     ensure_ascii=False, indent=2))
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "…")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
