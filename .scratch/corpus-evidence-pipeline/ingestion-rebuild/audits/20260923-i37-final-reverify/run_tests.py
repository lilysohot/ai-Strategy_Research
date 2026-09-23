"""I3-7 测试电池（M4/M5 门重验 lane runner）：对 I3-6 冻结版本执行可复现 pytest lane。

按 ``i3-final-freeze-manifest.json`` 的 m4_m5_gates_to_reverify 执行（9 组中的测试组；
负例双口径由 i37_score.py 覆盖、legacy 非回归由 i37_legacy.py 覆盖、静态门单跑）。

lane 顺序（关键约束：M5 PG 各文件**逐用例 TRUNCATE 全 corpus schema**——I2 时代自含
沙箱设计；search_pg 的 `_live` 门需要既有语料多命中，故必须**最先**在 b1 重建的真实
8 源完好状态下运行；fullchain 为增量式（实测通过、不 TRUNCATE）；其余 9 文件自含）：

- M4-PLAIN：corpus 家族（test_corpus_preparation*.py 去 guard + gap_review +
  gap_dispositions + scoring + cli + cli_isolation）plain env（内存链；PG 用例无 DSN 自然 skip）；
- M4-I1：同家族 i1 守卫 env（零模型/零网络/六材料范围）；
- DEVLANE：``tests/test_corpus_dev_lane.py``（i3-e2e 守卫 env）；
- M5-SEARCH-LIVE：``tests/test_corpus_search_pg.py`` 单列首跑（真实 8 源完好，
  POOL_QUERY OR 串多命中）——i2-verify 守卫 env + ``CORPUS_I2_DSN``；
- FULLCHAIN-12：``audits/20260918-i2-fullchain-review/test_fullchain_probes.py``
  （write-once 不修改），i2-verify 守卫 env + ``CORPUS_I2_DSN``；
- M5-HERMETIC：publication_pg/repository_pg/authority/cli_pg/cli_isolation/
  consumers_pg/a1_ingest_search 七件（逐用例 TRUNCATE 自含）——同守卫 env；
- M5-DSN(D2/D6)：claims + metadata——**无守卫 env** 偏差 lane：D2/D6 走
  ``service.dsn()`` 真连接串，而 corpus 守卫对 ``CORPUS_DSN`` fail-closed 投毒
  （守卫 lane 下必 skip，实测 21 skip 即此来源）。另 D2/D6 为 legacy 形态用例
  （直插临时 schema 的 documents/blocks + legacy 句柄 fetch），设计前提是
  "目标库无 corpus schema ⇒ auto 探测判 legacy"；沙箱库含 corpus schema 使
  auto 必判 new 链（E2E fetch 冻结行为即拒 LegacyHandleError），强设 legacy
  又被 read_chain() 拒绝"新库禁静默降级"（两轮实测均 fail-closed，冻结行为
  本身正确，非产品缺陷）。故本 lane 在**隔离 543 容器内新建无 corpus schema
  的第三库 ``i2_d2d6_corpus``**（仅承载 legacy 形态表；生产库 5432 与沙箱
  i2_sandbox_corpus 零影响）忠实复现设计前提：``CORPUS_DSN`` → 第三库、
  ``CORPUS_I2_DSN`` → 沙箱（metadata ingest_path 写路径仍走引擎代理并受其
  fail-closed 目标校验）；``CORPUS_READ_CHAIN`` 保持冻结默认 auto（探测第三库
  自然判 legacy）。零模型由测试假实现注入保证；
- 恢复步：电池启动时自愈前置（清残留第三库 + 预恢复真实 8 源，防上轮中途崩溃
  留下无 schema 中间态），lane 结束后内联复跑 i37_rebuild.py 流水线
  （teardown+apply+播种+build/check/publish+gap-review；重建确定性 ⇒ build_id
  逐一复现），产物写临时文件不覆盖 write-once 的 rebuild-report.json；恢复前
  先 DROP 第三库（i2s1_apply._check_target_instance 对实例库集合 fail-closed，
  冻结资产不可扩）；**两次恢复均经 ``--restore`` 独立子进程执行**——恢复会装
  i3-e2e 守卫，若留在父进程将经 Popen 引导向 lane 子进程注入父配置（前轮实测：
  换装被拒 + CORPUS_DSN 被投毒成哨兵），父进程必须全程保持不装守卫；
- 终检：恢复后 8 源 build_id 与 rebuild-report 严格一致且 active 指针严格等于
  8 源集合（teardown 重建后测试残留清零）。

纪律：零模型（守卫 lane 全部经 env 声明阶段守卫禁模型面；D2/D6 偏差 lane 零模型由
假实现注入保证）；父进程为不装守卫的可信 runner（同 run_checks.py 先例——父进程
装守卫会经 Popen 引导向子进程注入父配置，导致子 lane 换装被拒）；
lane 日志逐 lane 落盘（覆盖），汇总 ``i37-tests-results.json`` write-once。
用法（仓库根）： uv run python .scratch/.../audits/20260923-i37-final-reverify/run_tests.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
GUARD_I2V = BASE / "guards/i2-verify.json"
GUARD_I1 = BASE / "guards/i1.json"
GUARD_E2E = BASE / "guards/i3-e2e.json"
REBUILD_REPORT = HERE / "rebuild-report.json"
SANDBOX_DB = "i2_sandbox_corpus"
D2D6_DB = "i2_d2d6_corpus"
sys.path.insert(0, str(ROOT))


def build_dsn() -> str:
    env = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    )
    cred = env["CORPUS_DSN"].split("://", 1)[1].rsplit("@", 1)[0]
    return f"postgresql://{cred}@127.0.0.1:543/{SANDBOX_DB}"


def build_admin_cred() -> str:
    env = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    )
    return env["CORPUS_DSN"].split("://", 1)[1].rsplit("@", 1)[0]


def ensure_d2d6_db() -> str:
    """隔离 543 容器内确保存在无 corpus schema 的第三库（D2/D6 legacy 形态前提）。"""
    import psycopg

    cred = build_admin_cred()
    admin = f"postgresql://{cred}@127.0.0.1:543/postgres"
    target = f"postgresql://{cred}@127.0.0.1:543/{D2D6_DB}"
    with psycopg.connect(admin, autocommit=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (D2D6_DB,)
        ).fetchone()
        if row is None:
            conn.execute(f'CREATE DATABASE "{D2D6_DB}"')
    with psycopg.connect(target, autocommit=True) as conn:
        present = conn.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'corpus'"
        ).fetchone()
        if present is not None:
            raise SystemExit(f"{D2D6_DB} 意外含有 corpus schema（拒绝作为 legacy 形态库）")
    return target


def lane_env(*, guard: Path | None, dsn: str | None, also_corpus_dsn: bool = False) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    if guard is not None:
        env["CORPUS_GUARD_PHASE"] = guard.stem
        env["CORPUS_GUARD_CONFIG"] = str(guard)
    if dsn is not None:
        env["CORPUS_I2_DSN"] = dsn
        if also_corpus_dsn:
            env["CORPUS_DSN"] = dsn
    return env


def family_tests() -> list[str]:
    tests = sorted(str(p.relative_to(ROOT))
                   for p in (ROOT / "tests").glob("test_corpus_preparation*.py"))
    tests.remove("tests/test_corpus_preparation_guard.py")
    tests += ["tests/test_corpus_gap_review.py", "tests/test_corpus_gap_dispositions.py",
              "tests/test_corpus_scoring.py", "tests/test_corpus_cli.py",
              "tests/test_corpus_cli_isolation.py"]
    return tests


M5_HERMETIC_TESTS = [
    "tests/test_corpus_preparation_publication_pg.py",
    "tests/test_corpus_preparation_repository_pg.py",
    "tests/test_corpus_authority_pg.py",
    "tests/test_corpus_cli_pg.py",
    "tests/test_corpus_cli_isolation.py",
    "tests/test_corpus_consumers_pg.py",
    "tests/test_corpus_a1_ingest_search.py",
]

M5_DSN_TESTS = [
    "tests/test_corpus_claims.py",
    "tests/test_corpus_metadata.py",
]


def parse_counts(text: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    m = re.search(r"(\d+) passed", text)
    if m:
        counts["passed"] = int(m.group(1))
    m = re.search(r"(\d+) failed", text)
    if m:
        counts["failed"] = int(m.group(1))
    m = re.search(r"(\d+) skipped", text)
    if m:
        counts["skipped"] = int(m.group(1))
    m = re.search(r"(\d+) error", text)
    if m:
        counts["errors"] = int(m.group(1))
    return counts


def run_lane(label: str, tests: list[str], env: dict[str, str]) -> dict[str, object]:
    args = [sys.executable, "-B", "-m", "pytest", "--noconftest", "-c", "/dev/null",
            "-p", "no:cacheprovider", "-p", "plugins.corpus.preparation.guard_pytest",
            "-q", "--tb=short", "-ra", "--basetemp", str(HERE / f"{label}-tmp"), *tests]
    proc = subprocess.run(args, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=1800)
    text = proc.stdout + f"\nexit={proc.returncode}\n"
    (HERE / f"lane-{label}.txt").write_text(text, encoding="utf-8")
    counts = parse_counts(text)
    return {
        "lane": label,
        "exit_code": proc.returncode,
        "counts": counts,
        "guard": env.get("CORPUS_GUARD_PHASE", "plain"),
        "dsn_set": "CORPUS_I2_DSN" in env,
        "corpus_dsn_set": "CORPUS_DSN" in env,
        "tests": tests if len(tests) <= 12 else [f"{len(tests)} files"],
        "log": f"lane-{label}.txt",
    }


def load_i37_rebuild():
    spec = importlib.util.spec_from_file_location("i37_rebuild_mod", HERE / "i37_rebuild.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def drop_d2d6_db() -> bool:
    """电池收尾前删除第三库：i2s1_apply._check_target_instance 对实例数据库集合
    fail-closed（EXPECTED_CONTAINER_DBS 为冻结资产不可扩），故恢复步前必须还原。"""
    import psycopg

    cred = build_admin_cred()
    admin = f"postgresql://{cred}@127.0.0.1:543/postgres"
    with psycopg.connect(admin, autocommit=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (D2D6_DB,)
        ).fetchone()
        if row is not None:
            conn.execute(f'DROP DATABASE "{D2D6_DB}" WITH (FORCE)')
            return True
    return False


def restore_real_sources() -> dict[str, object]:
    """内联复跑 b1 重建流水线恢复真实 8 源（产物走临时文件，不动 write-once 报告）。"""
    rb = load_i37_rebuild()
    tmp_json = HERE / "restore-report.tmp.json"
    tmp_md = HERE / "restore-report.tmp.md"
    for p in (tmp_json, tmp_md):
        if p.exists():
            p.unlink()
    rb.OUT, rb.OUT_MD = tmp_json, tmp_md
    rc = rb.main()
    record = json.loads(tmp_json.read_text(encoding="utf-8"))
    canon = json.loads(REBUILD_REPORT.read_text(encoding="utf-8"))
    expected = {r["build_id"] for r in canon["per_source"] if r.get("build_id")}
    got = {r["build_id"] for r in record["per_source"] if r.get("build_id")}
    active = {r["build_id"] for r in record["per_source"] if r.get("active") and r.get("build_id")}
    for p in (tmp_json, tmp_md):
        p.unlink(missing_ok=True)
    return {
        "restore_exit_code": rc,
        "expected_real_builds": len(expected),
        "build_ids_deterministic": bool(rc == 0 and got == expected),
        "active_set_strict_match": active == expected,
        "missing_active": sorted(expected - active),
        "extra_active": sorted(active - expected),
        "published": record.get("summary", {}).get("published"),
        "active": record.get("summary", {}).get("active"),
        "note": "teardown 重建后测试残留清零；active 指针须严格等于真实 8 源",
    }


def restore_via_subprocess() -> dict[str, object]:
    """经独立子进程执行恢复（子进程内装 i3-e2e 守卫并随进程退出，父进程不装守卫）。"""
    proc = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--restore"],
        cwd=ROOT, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                       "LANG": "C.UTF-8", "PYTHONPATH": str(ROOT),
                       "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=1200,
    )
    (HERE / "lane-restore.txt").write_text(proc.stdout + f"\nexit={proc.returncode}\n",
                                           encoding="utf-8")
    if proc.returncode != 0:
        return {"restore_exit_code": proc.returncode,
                "build_ids_deterministic": False, "active_set_strict_match": False,
                "stderr_tail": proc.stdout[-800:]}
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return dict(payload)


def main() -> int:
    dsn = build_dsn()
    # 自愈前置：清残留第三库并预恢复真实 8 源（上轮若在恢复步中途崩溃，沙箱可能
    # 处于无 corpus schema 的中间态；电池必须从 b1 良好态启动）。
    drop_d2d6_db()
    pre = restore_via_subprocess()
    d2d6_dsn = ensure_d2d6_db()
    family = family_tests()
    fullchain = [
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-fullchain-review/test_fullchain_probes.py",
    ]

    lanes = [
        ("m4-plain", family, lane_env(guard=None, dsn=None)),
        ("m4-i1", family, lane_env(guard=GUARD_I1, dsn=None)),
        ("dev-lane", ["tests/test_corpus_dev_lane.py"], lane_env(guard=GUARD_E2E, dsn=None)),
        ("m5-search-live", ["tests/test_corpus_search_pg.py"], lane_env(guard=GUARD_I2V, dsn=dsn)),
        ("fullchain-12", fullchain, lane_env(guard=GUARD_I2V, dsn=dsn)),
        ("m5-hermetic", M5_HERMETIC_TESTS, lane_env(guard=GUARD_I2V, dsn=dsn)),
        ("m5-dsn-d2d6", M5_DSN_TESTS, {**lane_env(guard=None, dsn=None),
                                       "CORPUS_DSN": d2d6_dsn,
                                       "CORPUS_I2_DSN": dsn}),
    ]
    results = [run_lane(label, tests, env) for label, tests, env in lanes]
    d2d6_dropped = drop_d2d6_db()
    pointers = restore_via_subprocess()
    pointers["d2d6_db_dropped_before_restore"] = d2d6_dropped
    by_label = {r["lane"]: r for r in results}

    def clean(label: str, *, zero_skip: bool) -> bool:
        r = by_label[label]
        ok = r["exit_code"] == 0 and r["counts"]["failed"] == 0 and r["counts"]["errors"] == 0
        return bool(ok and (r["counts"]["skipped"] == 0 if zero_skip else True))

    gates = {
        "fullchain_12_pass": (by_label["fullchain-12"]["exit_code"] == 0
                              and by_label["fullchain-12"]["counts"]["passed"] == 12
                              and by_label["fullchain-12"]["counts"]["skipped"] == 0),
        "m4_plain_pass": clean("m4-plain", zero_skip=False),
        "m4_i1_pass": clean("m4-i1", zero_skip=False),
        "dev_lane_pass": clean("dev-lane", zero_skip=False),
        "m5_search_live_pass_zero_skip": clean("m5-search-live", zero_skip=True),
        "m5_hermetic_pass_zero_skip": clean("m5-hermetic", zero_skip=True),
        "m5_dsn_d2_d6_pass_zero_skip": clean("m5-dsn-d2d6", zero_skip=True),
        "pre_restore_ready": bool(pre["build_ids_deterministic"]
                                  and pre["active_set_strict_match"]),
        "restore_deterministic_build_ids": bool(pointers["build_ids_deterministic"]),
        "real_sources_active_strict": bool(pointers["active_set_strict_match"]),
    }
    summary = {
        "artifact": "i37-final-reverify-tests",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "frozen_version": {
            "final_manifest": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-final-freeze-manifest.json",
            "chain_head_declared": "i0c-r4z",
            "chain_binding_revision": "i0c-r5a",
        },
        "env": {
            "dsn": f"postgresql://***@127.0.0.1:543/{SANDBOX_DB}",
            "d2d6_dsn": f"postgresql://***@127.0.0.1:543/{D2D6_DB}（无 corpus schema，legacy 形态前提库）",
            "guards": {"i2-verify": str(GUARD_I2V.relative_to(ROOT)),
                       "i1": str(GUARD_I1.relative_to(ROOT)),
                       "i3-e2e": str(GUARD_E2E.relative_to(ROOT))},
            "parent_guard": "无（父进程可信 runner；各 lane 子进程经 env 声明阶段守卫）",
        },
        "lanes": results,
        "pre_restore": pre,
        "restore_and_pointer_recheck": pointers,
        "gates": gates,
        "passed": all(gates.values()),
        "discipline": {
            "model_calls": 0,
            "db": "沙箱 127.0.0.1:543/i2_sandbox_corpus（M5 自含 lane 逐用例 TRUNCATE）＋"
                  "第三库 i2_d2d6_corpus（D2/D6 legacy 形态前提，无 corpus schema）；"
                  "生产库 5432 零触碰",
            "d2_d6_deviation": "claims/metadata 的 PG 用例走 service.dsn()，corpus 守卫对 "
                               "CORPUS_DSN fail-closed 投毒（守卫 lane 下必 skip，前轮实测 21 skip "
                               "即此来源）→ 无守卫 lane 运行，零模型由测试假实现注入保证；"
                               "D2/D6 另为 legacy 形态用例（legacy 句柄 fetch），沙箱含 corpus "
                               "schema 使 auto 判 new 链即拒、强设 legacy 亦被拒（两轮实测均 "
                               "fail-closed，冻结行为正确非产品缺陷）→ 在隔离 543 容器内新建"
                               "无 corpus schema 第三库 i2_d2d6_corpus 忠实复现设计前提，"
                               "生产库 5432 与沙箱零影响",
            "lane_order": "search_pg _live 门需既有语料多命中故首跑；M5 自含 lane 逐用例 "
                          "TRUNCATE 全 schema，故全部 destructive lane 排后并以内联重建收尾恢复真实 8 源",
            "test_files": "write-once 不修改（fullchain 12 项照原样执行）",
        },
    }
    out = HERE / "i37-tests-results.json"
    if out.exists():
        raise SystemExit(f"write-once 冲突：{out} 已存在")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"lanes": [{k: r[k] for k in ("lane", "exit_code", "counts")}
                                for r in results],
                      "pointers": pointers, "gates": gates,
                      "passed": summary["passed"]},
                     ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    if "--restore" in sys.argv[1:]:
        print(json.dumps(restore_real_sources()))
        raise SystemExit(0)
    raise SystemExit(main())
