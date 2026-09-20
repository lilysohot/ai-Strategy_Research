"""议题 B 重摄入（reader-pdf-6 + chunk-3 + index-4-zhcfg-2）：teardown 重建后全量重跑。

- 目的：议题 B（结构化召回与排序）改动（票 04 TableModel + label_path 入索引文本 +
  结构重叠排序信号）后，对沙箱全部 8 份 dev 来源重做 parse→clean→chunk→publish，
  使 PG 活动 build 反映新口径（reader-pdf-6 / chunk-3 / index-4-zhcfg-2），用于
  同口径回测（t8：图 6 十条引文进入选择范围、负例不回升）。
- 路径：**teardown 重建沙箱再全量重跑**（沿用 i35 受支持重建路径，U 2026-09-20 决策）。
  原地重摄入会因 write-once admission 冲突失败（reader 变更 → probe 派生
  metadata_snapshot 变化 → 同 decision_id 内容不同被拒）。
- 守卫：`guards/i3-e2e.json`（允许路径 8 份；网络仅 127.0.0.1:543；CORPUS_DSN 投毒）。
- dev lane：两份 dev 来源（工业富联 md / 光模块 docx）装载需 CORPUS_DEV_LANE=1。
- 播种逻辑移植自 run_i3_1_dev_lane.py（含 dev lane 两条取代链），保证审查绑定齐备。

用法(仓库根)::

    uv run python .scratch/.../audits/20260920-i42-topic-b-reingest/reingest.py
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
SANDBOX_DB = "i2_sandbox_corpus"
OUT = HERE / "reingest-report.json"
OUT_MD = HERE / "reingest-report.md"
OWNER = "i42-topic-b-reingest"
NOW = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
REVIEWER = "U（2026-09-20 会话裁决：议题 B 结构信号重摄入）"
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
    """返回 (admin_dsn, sandbox_dsn)；均指向 127.0.0.1:543（corpus-db 容器）。"""
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
                    rationale="I3-1 第二轮：U 2026-09-15 批准集（逐字保留）",
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
        "artifact": "i42-topic-b-reingest",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "reader_rev_before": "reader-pdf-5",
        "reader_rev_after": "reader-pdf-6",
        "chunk_rev_before": "chunk-2",
        "chunk_rev_after": "chunk-3",
        "index_rev_before": "index-3-zhcfg-2",
        "index_rev_after": "index-4-zhcfg-2",
        "path": "teardown 重建沙箱再全量重跑（沿用 i35 受支持路径）",
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
    sys.path.insert(0, str(HERE.parents[1] / "i2"))
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
        "all_new_build_active": all(
            r.get("active") for r in per_source if r.get("build_id")
        ),
    }

    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# I42 议题 B 重摄入（reader-pdf-6 / chunk-3 / index-4-zhcfg-2，teardown 重建）",
        "",
        f"- 生成：{record['generated_at']}；清单 `{record['scope']['manifest']}`"
        f"（sha256 {record['scope']['manifest_sha256'][:12]}，{record['scope']['size']} 份）",
        f"- 版本：reader {record['reader_rev_before']} → **{record['reader_rev_after']}**；"
        f"chunk {record['chunk_rev_before']} → **{record['chunk_rev_after']}**；"
        f"index {record['index_rev_before']} → **{record['index_rev_after']}**",
        f"- 路径：{record['path']}",
        f"- teardown：exit {record['steps']['teardown']['exit_code']}"
        f"（{record['steps']['teardown']['output']}）",
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
        f"- index_rev：{json.dumps(s['index_revs'], ensure_ascii=False)}；"
        f"chunk_rev：{json.dumps(s['chunk_revs'], ensure_ascii=False)}；"
        f"**全部新 build 成为 active：{s['all_new_build_active']}**",
        "- 说明：teardown 重建后代码全部重解析；新 build 因 parse_rev/chunk_rev/index_rev "
        "变更产生新 build_id。",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"summary": s, "build": record["build"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
