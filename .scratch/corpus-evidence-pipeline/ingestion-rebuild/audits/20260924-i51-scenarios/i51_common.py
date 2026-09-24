"""I5-1 四场景共享运行库（M8；守卫 lane 内运行，零模型，生产只读）。

纪律（r5n m8_kickoff + U 2026-09-24 批准范围）：
- 守卫先装（guards/i5-scenarios.json）；CORPUS_TARGET_DB=<场景一次性库> 在导入
  plugins 模块**之前**设置（pg_target 唯一开关；.env 携带 CORPUS_TARGET_DB=postgres，
  本库显式覆盖，隔离库不连生产）；
- 生产 pg 容器 5432 **仅只读**快照（SET TRANSACTION READ ONLY），前后各采一次；
- 凭据自 .env 读取（守卫安装前），不落入任何产物；
- 4 份 gap-review 已签署记录按 build_id 前十六位复用（I3-7/I4-4 先例，
  audits/20260920-i42-topic-b-reingest/signed-*.json）。
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
from typing import Any

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
GUARD = BASE / "guards/i5-scenarios.json"
MANIFEST = BASE / "audits/20260920-i31-dev-lane/dev-scope-manifest.json"
DEV_POLICY = BASE / "audits/20260920-i31-dev-lane/admission-policy-dev.json"
SIGNED_DIR = BASE / "audits/20260920-i42-topic-b-reingest"
I44_REPORT = BASE / "audits/20260923-i4-window/i44-rebuild-report.json"
PROD_HOST, PROD_PORT, PROD_DB = "127.0.0.1", 5432, "postgres"
ISO_HOST, ISO_PORT = "127.0.0.1", 543

PROD_COUNTS_SQL = (
    "SELECT (SELECT count(*) FROM corpus.corpus_sources) AS sources,"
    " (SELECT count(*) FROM corpus.corpus_review_decisions) AS decisions,"
    " (SELECT count(*) FROM corpus.corpus_builds) AS builds,"
    " (SELECT count(*) FROM corpus.corpus_chunks) AS chunks,"
    " (SELECT count(*) FROM corpus.corpus_units) AS units,"
    " (SELECT count(*) FROM corpus.corpus_publications) AS publications,"
    " (SELECT count(*) FROM corpus.corpus_publications WHERE active_build_id IS NOT NULL) AS active"
)


def load_env_credentials() -> dict[str, str]:
    """守卫安装前读取 .env 凭据（CORPUS_DB_USER/CORPUS_DB_PASSWORD）。"""
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    for key in ("CORPUS_DB_USER", "CORPUS_DB_PASSWORD"):
        if not env.get(key):
            raise SystemExit(f"拒绝：.env 缺 {key}")
    return env


def install_guard(scenario_db: str):
    """设置隔离目标与 dev lane 开关 → 装守卫 → 导入并返回插件模块。"""
    os.environ["CORPUS_TARGET_DB"] = scenario_db
    os.environ["CORPUS_DEV_LANE"] = "1"
    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard as guard_module  # noqa: PLC0415

    guard_module.install(GUARD)
    from plugins.corpus import cli  # noqa: PLC0415
    from plugins.corpus.preparation.pg_target import resolve_target_db  # noqa: PLC0415

    resolved = resolve_target_db()
    if resolved != scenario_db:
        raise SystemExit(f"拒绝：resolve_target_db()={resolved!r} ≠ {scenario_db!r}")
    return cli, resolved


def iso_dsn(creds: dict[str, str], db: str) -> str:
    return f"postgresql://{creds['CORPUS_DB_USER']}:{creds['CORPUS_DB_PASSWORD']}@{ISO_HOST}:{ISO_PORT}/{db}"


def prod_dsn(creds: dict[str, str]) -> str:
    return f"postgresql://{creds['CORPUS_DB_USER']}:{creds['CORPUS_DB_PASSWORD']}@{PROD_HOST}:{PROD_PORT}/{PROD_DB}"


def prod_readonly_snapshot(dsn: str) -> dict[str, Any]:
    """生产只读快照：计数 + 逐源活动 build_id。任何写路径都会被只读事务拒绝。"""
    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(PROD_COUNTS_SQL)
        counts = dict(zip([d[0] for d in cur.description], cur.fetchone()))
        cur.execute(
            "SELECT c.source_id, p.active_build_id FROM corpus.corpus_publications p"
            " JOIN corpus.corpus_sources c ON c.source_id = p.source_id"
            " ORDER BY 1"
        )
        active = {row[0]: row[1] for row in cur.fetchall()}
    return {"counts": counts, "active_by_source": active}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cli_run(cli: Any, argv: list[str]) -> dict[str, Any]:
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


def seed_decisions(store: Any, sources: list[dict], dev_by_path: dict[str, dict],
                   creds: dict[str, str], *, decision_prefix: str | None, now: datetime,
                   rationale_tag: str, path_override: dict[str, str] | None = None) -> list[dict]:
    """播种 8 份审查决定（6 approved + 2×2 dev lane 取代链），路径可映射到变异副本。

    ``decision_prefix=None`` 沿用 manifest 引用的**原始决定 id**（场景一/三/四，
    决定链与生产 I4-4 逐字一致）；非 None 时生成新 id（场景二变异副本：新
    source_id 绑定新决定 id，manifest 同步携带新 id）。
    """
    from plugins.corpus.preparation.contract import (  # noqa: PLC0415
        MaterialType,
        ResearchDomain,
        ReviewDecision,
        ReviewedDecision,
        sha256_of_bytes,
    )

    seeded: list[dict] = []
    for entry in sources:
        orig_path = str(entry["path"])
        path = (path_override or {}).get(orig_path, orig_path)
        source_id = sha256_of_bytes((ROOT / path).read_bytes())
        domain = ResearchDomain(str(entry["domain_hint"]))
        ids = list(entry["review_decision_ids"])
        new_ids = ([f"{decision_prefix}-{i}" for i in ids]
                   if decision_prefix else [str(i) for i in ids])
        if entry.get("provenance") == "approved_set":
            store.put_reviewed_decision(
                ReviewedDecision(
                    decision_id=new_ids[0],
                    source_id=source_id,
                    reviewer="I5-1（U 2026-09-24 批准范围；批准集 U 2026-09-15 属性逐字保留）",
                    reviewed_at=now,
                    decision=ReviewDecision.ADMITTED,
                    rationale=f"{rationale_tag}：{orig_path}（属性保留，新 source_id 绑定）",
                    research_domain=domain,
                )
            )
            seeded.append({"orig_path": orig_path, "path": path, "decisions": new_ids,
                           "kind": "approved_set"})
        else:
            lane = dev_by_path[orig_path]
            material = MaterialType(str(lane["material_type"]))
            store.put_reviewed_decision(
                ReviewedDecision(
                    decision_id=new_ids[0],
                    source_id=source_id,
                    reviewer="U（i0a2-adjudicated-20260915.json）",
                    reviewed_at=datetime(2026, 9, 15, 8, 20, 52, tzinfo=UTC),
                    decision=ReviewDecision(str(lane["i0a2_decision"])),
                    rationale=str(lane["i0a2_note"]),
                    material_type=material,
                )
            )
            store.put_reviewed_decision(
                ReviewedDecision(
                    decision_id=new_ids[1],
                    source_id=source_id,
                    reviewer="I5-1（U 2026-09-24 批准范围；dev lane U 2026-09-20 属性逐字保留）",
                    reviewed_at=now,
                    decision=ReviewDecision.ADMITTED,
                    rationale=(f"{rationale_tag}：dev lane（{lane['reason'][:80]}）"),
                    material_type=material,
                    research_domain=domain,
                    supersedes=new_ids[0],
                )
            )
            seeded.append({"orig_path": orig_path, "path": path, "decisions": new_ids,
                           "kind": "dev_lane", "material_type": str(lane["material_type"])})
    return seeded


def write_manifest(out_path: Path, sources: list[dict], *, note: str) -> None:
    """生成场景 manifest（policy 字段沿用 dev lane 政策路径）。"""
    payload = {
        "note": note,
        "policy": str(DEV_POLICY.relative_to(ROOT)),
        "sources": sources,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_check_publish(cli: Any, dsn: str, manifest: Path, archive: Path, owner: str,
                        baseline_rows: dict[str, dict], *, gap_review: bool) -> tuple[dict, list[dict]]:
    """build → check →（可选 signed gap-review 后重查）→ publish；逐源返回对照行。"""
    archive.mkdir(parents=True, exist_ok=True)
    build = cli_run(cli, ["build", "--manifest", str(manifest), "--dsn", dsn,
                          "--owner", owner, "--archive-root", str(archive)])
    outcomes = {str(o.get("original_name")): o for o in (build["output"] or {}).get("outcomes") or []}
    per_source: list[dict] = []
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["sources"]:
        name = Path(str(entry["path"])).name
        outcome = outcomes.get(name) or {}
        row: dict[str, Any] = {
            "orig_path": str(entry["path"]),
            "original_name": name,
            "decision": outcome.get("decision"),
            "decision_id": outcome.get("decision_id"),
            "source_id": outcome.get("source_id"),
            "build_id": outcome.get("build_id"),
            "unit_count": outcome.get("unit_count"),
            "chunk_count": outcome.get("chunk_count"),
            "source_reused": outcome.get("source_reused"),
            "archive_reused": outcome.get("archive_reused"),
        }
        if outcome.get("decision") == "in_scope" and outcome.get("build_id"):
            checked = cli_run(cli, ["check", "--build", str(outcome["build_id"]), "--dsn", dsn])
            row["check_exit"] = checked["exit_code"]
            row["publishable"] = (checked["output"] or {}).get("publishable")
            row["blocking_gaps"] = [
                {"code": g.get("code"), "status": g.get("status")}
                for g in (checked["output"] or {}).get("gaps") or []
                if str(g.get("disposition")) not in ("acknowledged", "noise")
            ]
            if checked["exit_code"] == 0:
                published = cli_run(cli, ["publish", "--build", str(outcome["build_id"]),
                                          "--operator", owner, "--dsn", dsn])
                row["publish"] = {"exit_code": published["exit_code"],
                                  "generation": (published["output"] or {}).get("generation"),
                                  "active_build_id": (published["output"] or {}).get("active_build_id")}
            elif gap_review:
                signed = SIGNED_DIR / f"signed-{str(outcome['build_id'])[:16]}.json"
                if not signed.is_file():
                    row["gap_review"] = {"error": f"missing signed record: {signed.name}"}
                else:
                    applied = cli_run(cli, ["gap-review", "--build", str(outcome["build_id"]),
                                            "--record", str(signed), "--dsn", dsn])
                    row["gap_review"] = {"record": signed.name, "exit_code": applied["exit_code"]}
                    if applied["exit_code"] == 0:
                        rechecked = cli_run(cli, ["check", "--build", str(outcome["build_id"]),
                                                  "--dsn", dsn])
                        row["check_exit"] = rechecked["exit_code"]
                        row["publishable"] = (rechecked["output"] or {}).get("publishable")
                        if rechecked["exit_code"] == 0:
                            published = cli_run(cli, ["publish", "--build", str(outcome["build_id"]),
                                                      "--operator", owner, "--dsn", dsn])
                            row["publish"] = {"exit_code": published["exit_code"],
                                              "generation": (published["output"] or {}).get("generation"),
                                              "active_build_id": (published["output"] or {}).get("active_build_id"),
                                              "after_gap_review": True}
                        else:
                            row["publish"] = {"exit_code": rechecked["exit_code"], "blocked": True}
                    else:
                        row["publish"] = {"exit_code": applied["exit_code"], "blocked": True}
            else:
                row["publish"] = {"exit_code": checked["exit_code"], "blocked": True}
        base = baseline_rows.get(name) or {}
        row["i44_baseline"] = {
            "build_id": base.get("build_id"),
            "build_id_match": (base.get("build_id") == row.get("build_id")),
            "unit_count": base.get("unit_count"),
            "chunk_count": base.get("chunk_count"),
            "units_match": (base.get("unit_count") == row.get("unit_count")),
            "chunks_match": (base.get("chunk_count") == row.get("chunk_count")),
        }
        per_source.append(row)
    report = {"build": {"exit_code": build["exit_code"], "seconds": build["seconds"],
                        "count": (build["output"] or {}).get("count")},
              "per_source": per_source}
    return report, per_source


def iso_counts(dsn: str) -> dict[str, int]:
    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(PROD_COUNTS_SQL)
        return dict(zip([d[0] for d in cur.description], cur.fetchone()))


def assert_active_generation(store: Any, row: dict, *, want_active: bool) -> dict[str, Any]:
    b = store.get_build(row["build_id"]) if row.get("build_id") else None
    pub = store.get_publication(b.source_id) if b is not None else None
    return {"build_known": b is not None,
            "active": bool(pub and pub.active_build_id == row.get("build_id")) if pub else False,
            "generation": pub.generation if pub else None,
            "want_active_satisfied": (bool(pub and pub.active_build_id == row.get("build_id")) == want_active)}
