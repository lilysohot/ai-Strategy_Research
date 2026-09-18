"""I2-6 cli_isolation 族（真库 + 真实 CLI 子进程 + 零模型陷阱）。

依据：架构 §12.2 ``cli_isolation``（真实注册工具 + CLI 子进程往返、模型调用陷阱、
网络允许清单、重启续跑、未知句柄、错误退出码）+ §2.1（先于测试收集装载拒绝守卫；
模型客户端构造/调用触发即失败）+ tasks.md I2-6 验收门（旧来源路径不能兜底；零模型陷阱通过）。

子进程经守卫 ``subprocess.Popen`` 补丁注入同配置引导（父进程已装 i2-verify 守卫），
因此子进程内同样受模型/网络/文件边界约束——这本身就是要验证的行为。

运行条件：``CORPUS_I2_DSN`` → ``i2_sandbox_corpus``；无 DSN 模块级跳过。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

DSN = os.environ.get("CORPUS_I2_DSN", "")
if not DSN:
    pytest.skip("CORPUS_I2_DSN 未设置（非 I2 演练环境）", allow_module_level=True)

import psycopg  # noqa: E402  仅 I2 演练环境导入

from plugins.corpus.preparation.contract import (  # noqa: E402
    ReviewDecision,
    ReviewedDecision,
    sha256_of_bytes,
)
from plugins.corpus.preparation.repository import StoreError  # noqa: E402
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402

SANDBOX_DB = "i2_sandbox_corpus"
TABLES = (
    "corpus_source_checkpoints",
    "corpus_jobs",
    "corpus_publications",
    "corpus_chunks",
    "corpus_units",
    "corpus_builds",
    "corpus_admissions",
    "corpus_review_decisions",
    "corpus_sources",
)
REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests/fixtures/corpus_preparation/synthetic-company-report.md"
WORK = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/tmp"


@pytest.fixture(autouse=True)
def _clean_tables():
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        database = cur.fetchone()[0]
        if database != SANDBOX_DB:
            raise StoreError(f"拒绝清理：current_database={database!r} ≠ {SANDBOX_DB!r}")
        cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
        if "apodex" in {r[0] for r in cur.fetchall()}:
            raise StoreError("拒绝清理：目标实例含 apodex 库")
        cur.execute(f"TRUNCATE {', '.join(f'corpus.{t}' for t in TABLES)}")
    yield


def _run(
    argv: list[str], *, with_dsn: bool = True, timeout: int = 180
) -> subprocess.CompletedProcess:
    """真实子进程：sys.executable（守卫可注入）；返回 (returncode, stdout, stderr)。"""
    env = os.environ.copy()
    if with_dsn:
        env["CORPUS_I2_DSN"] = DSN
    else:
        env.pop("CORPUS_I2_DSN", None)
    return subprocess.run(
        [sys.executable, *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        cwd=str(REPO),
    )


def _run_code(code: str, *, timeout: int = 120) -> subprocess.CompletedProcess:
    return _run(["-c", code], timeout=timeout)


# ── 1. 真实 CLI 子进程：退出码与 JSON 载荷 ─────────────────────


def test_subprocess_cli_exit_codes() -> None:
    unknown = "0" * 64
    status = _run(["-m", "plugins.corpus.cli", "status", "--build", unknown, "--dsn", DSN])
    assert status.returncode == 5, status.stderr
    assert json.loads(status.stdout)["ok"] is False

    check = _run(["-m", "plugins.corpus.cli", "check", "--build", unknown, "--dsn", DSN])
    assert check.returncode == 5  # 与 status 同码（RM-I28-10）

    plan = _run(["-m", "plugins.corpus.cli", "plan", "--manifest", "/nonexistent.json"])
    assert plan.returncode == 2

    no_target = _run(["-m", "plugins.corpus.cli", "status", "--build", unknown], with_dsn=False)
    assert no_target.returncode == 3
    assert json.loads(no_target.stdout)["error"].startswith("拒绝")


def test_subprocess_cli_round_trip_and_resume(capsys: pytest.CaptureFixture[str]) -> None:
    """真实 CLI 子进程走 build→check→publish→status；重跑 build 走幂等续跑。"""
    WORK.mkdir(parents=True, exist_ok=True)
    archive_root = WORK / f"archive-iso-{uuid.uuid4().hex[:8]}"
    manifest_path = WORK / f"plan-iso-{uuid.uuid4().hex[:8]}.json"
    manifest_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "path": str(FIXTURE),
                        "domain_hint": "company",
                        "review_decision_ids": ["iso-r1"],
                    }
                ],
                "archive_root": str(archive_root),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = PgStore(DSN, sandbox_db=SANDBOX_DB)
    try:
        store.put_reviewed_decision(
            ReviewedDecision(
                "iso-r1",
                sha256_of_bytes(FIXTURE.read_bytes()),
                "i2s6-test",
                datetime(2026, 9, 18, 14, tzinfo=UTC),
                ReviewDecision.ADMITTED,
                "subprocess isolation fixture",
            )
        )
    finally:
        store.close()

    built = _run(
        ["-m", "plugins.corpus.cli", "build", "--manifest", str(manifest_path), "--dsn", DSN]
    )
    assert built.returncode == 0, built.stderr
    outcome = json.loads(built.stdout)["outcomes"][0]
    build_id = str(outcome["build_id"])
    assert outcome["decision"] == "in_scope" and outcome["source_reused"] is False

    # 重启续跑：同清单再跑一次 → 同 build、来源与归档复用（幂等，不重复增行）
    resumed = _run(
        ["-m", "plugins.corpus.cli", "build", "--manifest", str(manifest_path), "--dsn", DSN]
    )
    assert resumed.returncode == 0, resumed.stderr
    again = json.loads(resumed.stdout)["outcomes"][0]
    assert again["build_id"] == build_id
    assert again["source_reused"] is True and again["archive_reused"] is True

    checked = _run(["-m", "plugins.corpus.cli", "check", "--build", build_id, "--dsn", DSN])
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["publishable"] is True

    published = _run(
        [
            "-m",
            "plugins.corpus.cli",
            "publish",
            "--build",
            build_id,
            "--operator",
            "i2s6-subprocess",
            "--dsn",
            DSN,
        ]
    )
    assert published.returncode == 0, published.stderr
    payload = json.loads(published.stdout)
    assert payload["generation"] == 1 and payload["active_build_id"] == build_id
    assert payload["record"]["operator"] == "i2s6-subprocess"
    assert payload["record"]["generation"] == 1

    status = _run(["-m", "plugins.corpus.cli", "status", "--build", build_id, "--dsn", DSN])
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["next"] == "已发布"
    capsys.readouterr()  # 子进程输出不经父进程 capsys，保持断言显式


# ── 2. 零模型陷阱（子进程内同样生效）──────────────────────────


def test_subprocess_model_client_import_refused() -> None:
    result = _run_code("import openai\nprint('MODEL_IMPORTED')")
    assert result.returncode != 0
    assert "MODEL_IMPORTED" not in result.stdout
    assert "openai" in (result.stdout + result.stderr)

    constructed = _run_code("from openai import OpenAI\nOpenAI()\nprint('MODEL_CONSTRUCTED')")
    assert constructed.returncode != 0
    assert "MODEL_CONSTRUCTED" not in constructed.stdout


# ── 3. 网络允许清单（子进程）──────────────────────────────────


def test_subprocess_network_allowlist() -> None:
    blocked = _run_code(
        "import socket\n"
        "socket.create_connection(('203.0.113.1', 443), timeout=2)\n"
        "print('CONNECTED_OUTSIDE')"
    )
    assert blocked.returncode != 0
    assert "CONNECTED_OUTSIDE" not in blocked.stdout

    allowed = _run_code(
        "import socket\n"
        "s = socket.create_connection(('127.0.0.1', 543), timeout=5)\n"
        "s.close()\n"
        "print('ALLOWED_PG')"
    )
    assert allowed.returncode == 0, allowed.stderr
    assert "ALLOWED_PG" in allowed.stdout


# ── 4. 未知/旧句柄在子进程内同样拒绝（不回退旧来源）────────────


def test_subprocess_legacy_handle_refused() -> None:
    code = (
        "import os\n"
        "from plugins.corpus.preparation import read_pg\n"
        "try:\n"
        "    read_pg.fetch_verbatim(os.environ['CORPUS_I2_DSN'], '2026-09-09_legacy', 'chunk:x')\n"
        "    print('NOT_REFUSED')\n"
        "except read_pg.LegacyHandleError:\n"
        "    print('LEGACY_REFUSED')\n"
    )
    result = _run_code(code)
    assert result.returncode == 0, result.stderr
    assert "LEGACY_REFUSED" in result.stdout
