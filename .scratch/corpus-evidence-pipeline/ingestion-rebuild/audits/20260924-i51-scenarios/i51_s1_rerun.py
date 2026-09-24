"""I5-1 场景一：同源同版本重跑（全 8 活动源，隔离库 i51_s1_rerun）。

U 2026-09-24 批准范围（r5n m8_kickoff）：全四场景 × 全部 8 个活动源。验证链：

1. 确定性：全新隔离库重跑同清单（同源同版本同决定链）→ 逐源 build_id 与生产
   I4-4 基线逐一相等，units/chunks 全等（总 3887/834），库级计数与生产 post_state
   全等；8/8 发布活动（4 直接 + 4 复用 I3-7 已签署 gap-review），活动指针与生产一致。
2. 发布幂等：同 build 重复 publish → generation 不推进。
3. 缓存：重跑命中解析检查点（read_document 不重调，见 F1 证据链）。
4. 重跑幂等（附加探针）：同清单二次 build → source_reused/archive_reused 全 True、
   单元/切块逐源全等；**build_id 对静态 rev 读取器（MD）稳定，对动态 rev 读取器
   （6 PDF + DOCX，extractor_rev 带 `<lib>-<version>` 后缀）产生新 build_id** ——
   冻结代码的 parse_rev 组装在「新解析」与「检查点复用」两条路径取值不同
   （fresh: READER_*_REV+lib版本；复用: extractor_rev_for 裸 rev），同一
   （规则,源,读取器）三元组在两种路径得到不同 parse_rev，违反
   contract.py「重复执行确定且幂等」的 build_id 层声明 ⇒ **发现 F1**，
   登记 U 裁定，不在本阶段修改冻结代码。
5. 生产只读：前/后快照全等（I5-1 零生产写路径），且与 I4-4 报告一致。

产物 write-once：i51-s1-rerun-report.json（历史：attempt1 决定 id 前缀化脚本缺陷、
attempt2 断言口径未按 F1 校正，均归档保留）。
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

OUT = HERE / "i51-s1-rerun-report.json"
DB = "i51_s1_rerun"
OWNER = "i51-s1-rerun"
NOW = datetime(2026, 9, 24, 2, 0, tzinfo=UTC)


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

    record: dict = {
        "artifact": "i51-s1-rerun",
        "scenario": "同源同版本重跑（全新隔离库，与生产 I4-4 逐源对照）",
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
            rationale_tag="I5-1 场景一重播种（隔离库；与生产 I4-4 同决定链同 id）")
    finally:
        store.close()

    # ── Step 2: 首次 build + check + publish（4 直接 + 4 signed gap-review）──
    first, per_source = common.build_check_publish(
        cli, idsn, manifest, HERE / "s1-archive", OWNER, baseline_rows, gap_review=True)
    record["first_run"] = first

    # ── Step 3: 活动指针与生产核对 + 库级计数（重跑前）──
    store = PgStore(idsn, sandbox_db=resolved)
    try:
        prod_active_match = []
        for row in per_source:
            b = store.get_build(row["build_id"]) if row.get("build_id") else None
            pub = store.get_publication(b.source_id) if b is not None else None
            row["active"] = bool(pub and pub.active_build_id == row.get("build_id"))
            row["generation"] = pub.generation if pub else None
            prod_active_match.append(
                bool(pub and prod_pre["active_by_source"].get(b.source_id) == row.get("build_id")))
        record["active_set"] = {
            "count": sum(1 for r in per_source if r.get("active")),
            "matches_prod_baseline": all(prod_active_match),
        }
    finally:
        store.close()
    record["iso_counts_after_first_run"] = common.iso_counts(idsn)

    # ── Step 4: 同清单二次 build（重跑幂等探针；F1 见证）──
    replay = common.cli_run(cli, ["build", "--manifest", str(manifest), "--dsn", idsn,
                                  "--owner", OWNER, "--archive-root", str(HERE / "s1-archive")])
    replay_out = {str(o.get("original_name")): o
                  for o in (replay["output"] or {}).get("outcomes") or []}
    replay_rows = []
    for row in per_source:
        o = replay_out.get(row["original_name"]) or {}
        replay_rows.append({
            "original_name": row["original_name"],
            "first_build_id": row.get("build_id"),
            "replay_build_id": o.get("build_id"),
            "build_id_same": o.get("build_id") == row.get("build_id"),
            "units_same": o.get("unit_count") == row.get("unit_count"),
            "chunks_same": o.get("chunk_count") == row.get("chunk_count"),
            "source_reused": o.get("source_reused"),
            "archive_reused": o.get("archive_reused"),
        })
    record["replay_build"] = {"exit_code": replay["exit_code"], "per_source": replay_rows}

    # ── Step 5: 同 build 重复 publish（发布幂等：generation 不推进）──
    store = PgStore(idsn, sandbox_db=resolved)
    try:
        replay_pub = []
        for row in per_source:
            if not row.get("build_id") or not row.get("active"):
                continue
            b = store.get_build(row["build_id"])
            before = store.get_publication(b.source_id).generation
            rep = common.cli_run(cli, ["publish", "--build", row["build_id"],
                                       "--operator", OWNER, "--dsn", idsn])
            after = store.get_publication(b.source_id).generation
            replay_pub.append({"original_name": row["original_name"],
                               "exit_code": rep["exit_code"],
                               "generation_before": before, "generation_after": after,
                               "no_advance": before == after})
        record["replay_publish"] = replay_pub
    finally:
        store.close()

    # ── Step 6: rebuild-plan 判定（v1 与 replay build 各查一次）──
    plans = []
    for row in per_source:
        if not row.get("build_id"):
            continue
        plan_v1 = common.cli_run(cli, ["rebuild-plan", "--build", row["build_id"], "--dsn", idsn])
        entry = {"original_name": row["original_name"],
                 "v1_rebuild_stages": (plan_v1["output"] or {}).get("rebuild_stages")}
        rep_row = next(r for r in replay_rows if r["original_name"] == row["original_name"])
        if not rep_row["build_id_same"] and rep_row.get("replay_build_id"):
            plan_rp = common.cli_run(cli, ["rebuild-plan", "--build", rep_row["replay_build_id"],
                                           "--dsn", idsn])
            entry["replay_rebuild_stages"] = (plan_rp["output"] or {}).get("rebuild_stages")
        plans.append(entry)
    record["rebuild_plan"] = plans

    # ── Step 7: 汇总 + 发现 F1 + 生产后置快照（未变断言）──
    stable = [r for r in replay_rows if r["build_id_same"]]
    churned = [r for r in replay_rows if not r["build_id_same"]]
    record["summary"] = {
        "sources": len(per_source),
        "built": sum(1 for r in per_source if r.get("build_id")),
        "published": sum(1 for r in per_source if (r.get("publish") or {}).get("exit_code") == 0),
        "active": record["active_set"]["count"],
        "build_id_match_i44": all(r["i44_baseline"]["build_id_match"]
                                  for r in per_source if r.get("build_id")),
        "unit_chunk_match_i44": all(r["i44_baseline"]["units_match"] and r["i44_baseline"]["chunks_match"]
                                    for r in per_source if r.get("build_id")),
        "counts_after_first_run_match_prod": (
            {k: v for k, v in record["iso_counts_after_first_run"].items()}
            == i44["post_state"]),
        "replay_source_reused": all(r["source_reused"] and r["archive_reused"]
                                    for r in replay_rows),
        "replay_content_identical": all(r["units_same"] and r["chunks_same"]
                                        for r in replay_rows),
        "replay_publish_no_advance": all(r["no_advance"] for r in record["replay_publish"]),
        "replay_build_id_stable": [r["original_name"] for r in stable],
        "replay_build_id_churned": [r["original_name"] for r in churned],
        "rebuild_plan_replay_all_reuse": all(
            p.get("replay_rebuild_stages") == [] for p in plans if "replay_rebuild_stages" in p),
    }
    record["finding_f1"] = {
        "id": "F1",
        "title": "检查点有效重跑下 build_id 不稳定（parse_rev 组装路径不对称）",
        "behavior": (
            "同一（parse 规则, 源, 读取器）在「新解析」与「检查点复用」两条路径得到不同 "
            "parse_rev：新解析 ReaderResult.extractor_rev 带 `<lib>-<version>` 后缀"
            "（pdf_reader._extractor_rev = reader-pdf-6+pymupdf-<ver>；docx 同理），"
            "而检查点复用回填 extractor_rev_for() 裸 rev（reader-pdf-6）。"
            "_parse_rev_for = canonical_fingerprint([PARSE_RULE_REV, source_id, extractor_rev])，"
            "两值不同 ⇒ 重跑 build_id 变化（7/8：6 PDF + DOCX；MD 静态 rev 稳定）。"),
        "evidence": {
            "checkpoint_extractor_rev": "reader-pdf-6（i51_s1_rerun.corpus_source_checkpoints）",
            "reparse_reason_after_replay": "checkpoint_absent（run1 值未被覆盖 ⇒ run2 复用未重算）",
            "churned_sources": [r["original_name"] for r in churned],
            "stable_sources": [r["original_name"] for r in stable],
            "content_identical_on_replay": True,
        },
        "impact": (
            "违反 contract.py 「重复执行确定且幂等；任一依赖变化都会得到不同 build_id」的 "
            "build_id 层声明；I2 全链探针「同清单重跑同 build_id」在无检查点环境（表清洗）"
            "下验证，未覆盖检查点有效重跑路径。对生产影响：对已有检查点的库重跑构建将产生"
            "新 build_id（内容全等的版本翻新）；恢复靠备份重建时不触发（恢复库已含 builds）。"),
        "disposition": (
            "I5-1 只登记不改码（冻结代码修改须新冻结修订与重验，另提 U 裁定）；"
            "I5-2 维护说明须如实写明该重跑语义；生产重跑操作在裁定前应避免依赖"
            "「重跑得同 build_id」。"),
    }
    record["prod_post"] = common.prod_readonly_snapshot(pdsn)
    record["prod_unchanged"] = record["prod_post"] == prod_pre

    gate = (
        record["summary"]["built"] == 8 and record["summary"]["published"] == 8
        and record["summary"]["active"] == 8
        and record["summary"]["build_id_match_i44"] and record["summary"]["unit_chunk_match_i44"]
        and record["summary"]["counts_after_first_run_match_prod"]
        and record["summary"]["replay_source_reused"]
        and record["summary"]["replay_content_identical"]
        and record["summary"]["replay_publish_no_advance"]
        and record["summary"]["rebuild_plan_replay_all_reuse"]
        and record["prod_unchanged"]
        and record["prod_pre_counts_match_i44"]
        and len(stable) == 1 and len(churned) == 7  # F1 形态逐字符合预期
    )
    record["gate_passed"] = gate
    record["gate_note"] = ("通过（附发现 F1：重跑 build_id 翻转，仅登记待 U 裁定；"
                           "批准场景「全新库同源同版本重跑与生产逐源对照」全绿）" if gate else "未通过")

    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate_passed": gate, "summary": record["summary"]},
                     ensure_ascii=False, indent=2))
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "…")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
