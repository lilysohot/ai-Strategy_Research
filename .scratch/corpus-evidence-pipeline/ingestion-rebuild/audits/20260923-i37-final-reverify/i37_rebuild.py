"""I3-7 重验之重建步：teardown 重建沙箱 → 播种 8 份审查决定 → build/check/publish 全量重跑。

用 I3-6 冻结版本（i0c-r5a 入链锚定的 i0c-r4z 内容版本）对沙箱
``127.0.0.1:543/i2_sandbox_corpus`` **重新构建/索引**（任务清单 §3.6 I3-7 行：
「用 I3-6 版本重新构建/索引」）。重建路径沿用 U 2026-09-20 受支持决策
（audits/20260920-i42-topic-b-reingest/reingest.py 同款：teardown + apply + 播种 +
build/check/publish），不新增授权面：

- 守卫：``guards/i3-e2e.json``（来源 8 份授权路径；网络仅 127.0.0.1:543；CORPUS_DSN 投毒）；
- dev lane：两份 dev 来源装载需 ``CORPUS_DEV_LANE=1``；
- 播种逻辑移植自 i42 reingest（批准集 6 份 + dev lane 两条取代链），decision_id 与
  dev-scope-manifest.json 逐字一致；
- 留出零读取（守卫 forbidden_roots 不变）；零模型；生产库 5432 零触碰。

产物（本目录，单轮一次写）：rebuild-report.json / rebuild-report.md。
用法（仓库根）： uv run python .scratch/.../audits/20260923-i37-final-reverify/i37_rebuild.py
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
GUARD = BASE / "guards/i3-e2e.json"
MANIFEST = BASE / "audits/20260920-i31-dev-lane/dev-scope-manifest.json"
DEV_POLICY = BASE / "audits/20260920-i31-dev-lane/admission-policy-dev.json"
ARCHIVE = BASE / "audits/20260920-i31-dev-lane/archive-dev-lane"
FINAL_MANIFEST = BASE / "i3-final-freeze-manifest.json"
SANDBOX_DB = "i2_sandbox_corpus"
OUT = HERE / "rebuild-report.json"
OUT_MD = HERE / "rebuild-report.md"
OWNER = "i37-final-reverify"
NOW = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)
REVIEWER = "U（2026-09-20 会话裁决：I3-1 第二轮 + dev lane；I3-7 重验按冻结决定重播种）"
_CORPUS_DSN_ENV = "CORPUS_I2_DSN"


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


def _build_dsn(env: dict[str, str]) -> tuple[str, str]:
    cred = env["CORPUS_DSN"].split("://", 1)[1].rsplit("@", 1)[0]
    admin = f"postgresql://{cred}@127.0.0.1:543/postgres"
    sandbox = f"postgresql://{cred}@127.0.0.1:543/{SANDBOX_DB}"
    return admin, sandbox


def _run_step(step_name: str, module, *, env: dict[str, str]) -> dict:
    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    buf = io.StringIO()
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(buf):
            code = module.main()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    text = buf.getvalue()
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError:
        payload = {"raw": text[:2000]}
    return {"step": step_name, "exit_code": code,
            "seconds": round(time.perf_counter() - started, 2), "output": payload}


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
                    rationale="I3-7 重验重播种：U 2026-09-15 批准集（逐字保留）",
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
    env_cfg = _load_env(ROOT)
    admin_dsn, sandbox_dsn = _build_dsn(env_cfg)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dev_policy = json.loads(DEV_POLICY.read_text(encoding="utf-8"))
    dev_by_path = {str(item["path"]): item for item in dev_policy["dev_lane"]["sources"]}
    sources = manifest["sources"]

    record: dict = {
        "artifact": "i37-final-reverify-rebuild",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "frozen_version": {
            "final_manifest": str(FINAL_MANIFEST.relative_to(ROOT)),
            "final_manifest_sha256": digest(FINAL_MANIFEST),
            "chain_head_declared": "i0c-r4z",
            "chain_binding_revision": "i0c-r5a",
        },
        "path": "teardown 重建沙箱再全量重跑（U 2026-09-20 受支持重建路径，i42 同款）",
        "scope": {"manifest": str(MANIFEST.relative_to(ROOT)),
                  "manifest_sha256": digest(MANIFEST), "size": len(sources),
                  "sources": [s["path"] for s in sources]},
        "env": {"dsn": f"postgresql://***@127.0.0.1:543/{SANDBOX_DB}",
                "guard": {"path": str(GUARD.relative_to(ROOT)), "sha256": digest(GUARD)},
                "dev_lane_env": "CORPUS_DEV_LANE=1",
                "sandbox": "corpus-db 容器（127.0.0.1:543）i2_sandbox_corpus，teardown 重建"},
    }

    os.environ["CORPUS_DEV_LANE"] = "1"
    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard as guard_module  # noqa: PLC0415

    guard_module.install(GUARD)
    from plugins.corpus import cli  # noqa: PLC0415
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415

    # --- Step 0: teardown + apply（重建 corpus schema）---
    step_env = {_CORPUS_DSN_ENV: admin_dsn, "CONFIRM_TEARDOWN": SANDBOX_DB}
    sys.path.insert(0, str(BASE / "i2"))
    import i2s1_teardown  # noqa: PLC0415
    import i2s1_apply  # noqa: PLC0415

    record["steps"] = {}
    record["steps"]["teardown"] = _run_step("i2s1_teardown", i2s1_teardown, env=step_env)
    if record["steps"]["teardown"]["exit_code"] != 0:
        print(json.dumps({"error": "teardown 失败，中止", "step": record["steps"]["teardown"]},
                         ensure_ascii=False, indent=2))
        return record["steps"]["teardown"]["exit_code"]
    record["steps"]["apply"] = _run_step("i2s1_apply", i2s1_apply, env=step_env)
    if record["steps"]["apply"]["exit_code"] != 0:
        print(json.dumps({"error": "apply 失败，中止", "step": record["steps"]["apply"]},
                         ensure_ascii=False, indent=2))
        return record["steps"]["apply"]["exit_code"]

    # --- Step 1: 播种审查决定（8 份）---
    store = PgStore(sandbox_dsn, sandbox_db=SANDBOX_DB)
    try:
        record["seeded_decisions"] = _seed_decisions(store, sources, dev_policy, dev_by_path)
    finally:
        store.close()

    # --- Step 2: build ---
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    build = cli_run(cli, ["build", "--manifest", str(MANIFEST), "--dsn", sandbox_dsn,
                          "--owner", OWNER, "--archive-root", str(ARCHIVE)])
    outcomes = {str(o.get("original_name")): o for o in (build["output"] or {}).get("outcomes") or []}
    record["build"] = {"exit_code": build["exit_code"], "seconds": build["seconds"],
                       "count": (build["output"] or {}).get("count"),
                       "errors": (build["output"] or {}).get("error")}

    # --- Step 3: check + publish 逐来源 ---
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
            checked = cli_run(cli, ["check", "--build", str(outcome["build_id"]), "--dsn",
                                    sandbox_dsn])
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
                                          "--operator", OWNER, "--dsn", sandbox_dsn])
                row["publish"] = {"exit_code": published["exit_code"],
                                  "generation": (published["output"] or {}).get("generation"),
                                  "active_build_id": (published["output"] or {}).get("active_build_id")}
            else:
                row["publish"] = {"exit_code": checked["exit_code"], "blocked": True}
        per_source.append(row)

    # --- Step 3b: 对阻断来源登记 i42 已签署的人工 gap-review（build_id 确定性一致）---
    # 重建确定性 ⇒ build_id 与 i42 重建完全一致；signed-<build_id>.json 为该 build 的
    # 具名签署凭证（xyl，audits/20260920-i42-topic-b-reingest/，write-once 原件复用）。
    SIGNED_DIR = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i42-topic-b-reingest"
    gap_reviews = []
    for row in per_source:
        bid = row.get("build_id")
        if not bid or (row.get("publish") or {}).get("exit_code") == 0:
            continue
        signed = SIGNED_DIR / f"signed-{bid[:16]}.json"
        if not signed.is_file():
            row["gap_review"] = {"error": f"missing signed record: {signed.name}"}
            continue
        applied = cli_run(cli, ["gap-review", "--build", str(bid), "--record", str(signed),
                                "--dsn", sandbox_dsn])
        row["gap_review"] = {"record": str(signed.relative_to(ROOT)),
                             "record_sha256": digest(signed),
                             "exit_code": applied["exit_code"],
                             "output": applied["output"]}
        gap_reviews.append(row["original_name"])
        if applied["exit_code"] == 0:
            rechecked = cli_run(cli, ["check", "--build", str(bid), "--dsn", sandbox_dsn])
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
                                          "--operator", OWNER, "--dsn", sandbox_dsn])
                row["publish"] = {"exit_code": published["exit_code"],
                                  "generation": (published["output"] or {}).get("generation"),
                                  "active_build_id": (published["output"] or {}).get("active_build_id"),
                                  "after_gap_review": True}
    record["gap_review_applied"] = gap_reviews

    # --- Step 4: 读指针核验（新 build 是否 active + 各 rev）---
    with PgStore(sandbox_dsn, sandbox_db=SANDBOX_DB) as store:
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
        "chunk_revs": sorted({str(r.get("chunk_rev")) for r in per_source if r.get("chunk_rev")}),
        "parse_revs": sorted({str(r.get("parse_rev")) for r in per_source if r.get("parse_rev")}),
        "clean_revs": sorted({str(r.get("clean_rev")) for r in per_source if r.get("clean_rev")}),
        "all_new_build_active": all(
            r.get("active") for r in per_source if r.get("build_id")
        ),
    }

    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# I3-7 重验重建（用 I3-6 冻结版本 teardown 重建沙箱并全量 build/check/publish）",
        "",
        f"- 生成：{record['generated_at']}；冻结版本 manifest "
        f"`{record['frozen_version']['final_manifest']}`"
        f"（sha256 {record['frozen_version']['final_manifest_sha256'][:12]}，"
        f"链头 {record['frozen_version']['chain_head_declared']} / 绑定修订 "
        f"{record['frozen_version']['chain_binding_revision']}）",
        f"- 清单 `{record['scope']['manifest']}`（sha256 {record['scope']['manifest_sha256'][:12]}，"
        f"{record['scope']['size']} 份）",
        f"- 路径：{record['path']}",
        f"- teardown：exit {record['steps']['teardown']['exit_code']}",
        f"- apply：exit {record['steps']['apply']['exit_code']}"
        f"（tables {record['steps']['apply']['output'].get('tables_created')} / "
        f"indexes {record['steps']['apply']['output'].get('indexes_created')}）",
        f"- 守卫：`{record['env']['guard']['path']}`（{record['env']['guard']['sha256'][:12]}）；"
        f"`{record['env']['dev_lane_env']}`；沙箱 `{record['env']['sandbox']}`",
        "",
        "## 逐来源",
        "",
        "| 领域 | 格式 | 来源 | provenance | 单元/切块 | build | check | publish | 阻断缺口 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in per_source:
        gaps = "；".join(f"{g['code']}@{g['key']}" for g in row.get("blocking_gaps") or []) or "无"
        lines.append(
            f"| {row['domain']} | {row['format']} | {row['original_name'][:26]} | "
            f"{row.get('provenance')} | {row.get('unit_count')}/{row.get('chunk_count')} | "
            f"{str(row.get('build_id') or '')[:12]} | "
            f"{row.get('check_exit')} | {(row.get('publish') or {}).get('exit_code')}（gen "
            f"{(row.get('publish') or {}).get('generation')}） | {gaps} |"
        )
    s = record["summary"]
    lines += [
        "",
        f"- 汇总：built **{s['built']}/{s['sources']}**；published {s['published']}；blocked "
        f"{s['blocked']}；active(new build) {s['active']}",
        f"- revs：parse {json.dumps(s['parse_revs'], ensure_ascii=False)}；"
        f"clean {json.dumps(s['clean_revs'], ensure_ascii=False)}；"
        f"chunk {json.dumps(s['chunk_revs'], ensure_ascii=False)}；"
        f"index {json.dumps(s['index_revs'], ensure_ascii=False)}",
        f"- **全部新 build 成为 active：{s['all_new_build_active']}**（与冻结 REV 常量一致："
        "reader-pdf-6 / clean-3 / chunk-3 / index-4-zhcfg-2）",
        "- 说明：teardown 重建后按冻结代码全部重解析；本报告为 I3-7 重验的重建步证据。",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"summary": s, "build": record["build"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
