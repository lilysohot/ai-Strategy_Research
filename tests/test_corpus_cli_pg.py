"""I2-4 语料 CLI 真库往返：plan → build → check → publish(操作者/generation) → status。

运行条件：``CORPUS_I2_DSN`` 指向隔离库 ``i2_sandbox_corpus``（i2-verify 守卫 env）；
无 DSN 时模块级跳过。断言的是**实际读取/写入的目标与结果**（build_id、generation、
PUBLISHED job 检查点里的操作者），不是"命令能跑通"。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

DSN = os.environ.get("CORPUS_I2_DSN", "")
if not DSN:
    pytest.skip("CORPUS_I2_DSN 未设置（非 I2 演练环境）", allow_module_level=True)

import psycopg  # noqa: E402  仅 I2 演练环境导入

from plugins.corpus import cli  # noqa: E402
from plugins.corpus.preparation.contract import (  # noqa: E402
    Admission,
    AdmissionDecision,
    Build,
    DocumentFormat,
    MaterialType,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    Source,
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
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/corpus_preparation/synthetic-company-report.md"
)
ARCHIVE_PARENT = (
    Path(__file__).resolve().parents[1]
    / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/tmp"
)


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


@pytest.fixture()
def store() -> PgStore:
    instance = PgStore(DSN, sandbox_db=SANDBOX_DB)
    yield instance
    instance.close()


@pytest.fixture()
def archive_root() -> Path:
    root = ARCHIVE_PARENT / f"archive-cli-{uuid.uuid4().hex[:8]}"
    yield root
    # 不删目录：内容寻址归档是审计资产；测试隔离靠独立子目录名。


@pytest.fixture()
def prepared_build(archive_root: Path, capsys: pytest.CaptureFixture[str]) -> dict:
    """经 CLI 走完 build 命令，返回解析后的输出。"""
    store = PgStore(DSN, sandbox_db=SANDBOX_DB)
    try:
        store.put_reviewed_decision(
            ReviewedDecision(
                "cli-r1",
                sha256_of_bytes(FIXTURE.read_bytes()),
                "cli-test",
                datetime(2026, 9, 18, 10, tzinfo=UTC),
                ReviewDecision.ADMITTED,
                "synthetic whole-source admission",
            )
        )
    finally:
        store.close()
    manifest = archive_root.parent / f"cli-plan-{uuid.uuid4().hex[:8]}.json"
    archive_root.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "path": str(FIXTURE),
                        "domain_hint": "company",
                        "review_decision_ids": ["cli-r1"],
                    }
                ],
                "archive_root": str(archive_root),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(
        ["build", "--manifest", str(manifest), "--dsn", DSN, "--owner", "cli-test"]
    )
    assert exit_code == cli.EXIT_OK, capsys.readouterr().out
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["count"] == 1
    outcome = payload["outcomes"][0]
    assert outcome["decision"] == "in_scope" and outcome["build_id"]
    return {"build_id": str(outcome["build_id"]), "manifest": str(manifest)}


def test_cli_build_check_publish_status_round_trip(
    prepared_build: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    build_id = prepared_build["build_id"]

    # check：复用引擎发布门（只读），输出实际产物与活动指针
    assert cli.main(["check", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
    check = json.loads(capsys.readouterr().out)
    assert check["publishable"] is True
    assert check["unit_count"] > 0 and check["chunk_count"] > 0
    assert check["publication"] is None  # 尚未发布

    # publish：操作者与 generation 记入 PUBLISHED job 检查点（审计口径）
    assert cli.main(["publish", "--build", build_id, "--operator", "alice", "--dsn", DSN]) == (
        cli.EXIT_OK
    )
    published = json.loads(capsys.readouterr().out)
    assert published["generation"] == 1
    assert published["active_build_id"] == build_id
    assert published["record"]["operator"] == "alice"
    assert published["record"]["generation"] == 1

    # 幂等重放：同目标状态不递增 generation、不刷新时间
    assert cli.main(["publish", "--build", build_id, "--operator", "alice", "--dsn", DSN]) == (
        cli.EXIT_OK
    )
    replay = json.loads(capsys.readouterr().out)
    assert replay["generation"] == 1
    assert replay["activated_at"] == published["activated_at"]

    # status：阶段台账与活动指针（读的是该 build）
    assert cli.main(["status", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
    status = json.loads(capsys.readouterr().out)
    assert status["build_id"] == build_id and status["failed_stages"] == []
    assert status["publication"]["active_build_id"] == build_id
    assert status["next"] == "已发布"

    # rebuild-plan：规则版本未变 → 各阶段可复用（解析阶段标 unknown，须核源哈希）
    assert cli.main(["rebuild-plan", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
    plan = json.loads(capsys.readouterr().out)
    assert plan["rebuild_stages"] == []


def test_cli_unknown_build_exit_code_consistent_across_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RM-I28-10：同一前置条件（build 不存在）跨命令同码 = EXIT_UNAVAILABLE(5)。"""
    unknown = "0" * 64
    check_code = cli.main(["check", "--build", unknown, "--dsn", DSN])
    check_payload = json.loads(capsys.readouterr().out)
    status_code = cli.main(["status", "--build", unknown, "--dsn", DSN])
    status_payload = json.loads(capsys.readouterr().out)
    assert check_code == status_code == cli.EXIT_UNAVAILABLE
    for payload in (check_payload, status_payload):
        assert payload["ok"] is False and "build 不存在" in payload["error"]


def test_cli_rebuild_plan_follows_engine_parse_rev_api(
    store: PgStore, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """RM-I28-9：rebuild-plan 的 parse 复用判定只经引擎公开 API；引擎规则分量变化
    必须同步反映（证明 CLI 未自行拼一套公式），且非 MD 格式同样成立。"""
    from plugins.corpus.preparation import engine

    source = Source(
        source_id="a" * 64,
        format=DocumentFormat.DOCX,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=128,
        archive_path=f"ab/{'a' * 64}.docx",
        original_names=("nonmarkdown.docx",),
    )
    store.put_source(source)
    store.put_admission(
        Admission(
            decision_id="cli-docx-d1",
            source_id=source.source_id,
            material_type=MaterialType.RESEARCH_REPORT,
            research_domain=ResearchDomain.COMPANY,
            decision=AdmissionDecision.IN_SCOPE,
            policy_rev="v1-20260915",
        )
    )
    revs = engine.current_revs()
    build_id = sha256_of_bytes(b"i2s4:build:docx")
    store.put_build(
        Build(
            build_id=build_id,
            source_id=source.source_id,
            decision_id="cli-docx-d1",
            parse_rev=engine.expected_parse_rev(source),
            clean_rev=revs["clean_rev"],
            chunk_rev=revs["chunk_rev"],
            index_rev=revs["index_rev"],
            quality_report='{"gap_regions": [], "oversized_chunks": []}',
        )
    )
    assert cli.main(["rebuild-plan", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
    plan = json.loads(capsys.readouterr().out)
    assert plan["rebuild_stages"] == []  # DOCX 也判定可复用

    # 引擎规则分量变化 ⇒ 期望 parse_rev 变化 ⇒ CLI 判定同步转为 rebuild
    monkeypatch.setattr(engine, "PARSE_RULE_REV", "parse-9-review")
    assert cli.main(["rebuild-plan", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
    changed = json.loads(capsys.readouterr().out)
    assert changed["rebuild_stages"] == ["parse"]


def test_cli_rejects_production_target(capsys: pytest.CaptureFixture[str]) -> None:
    """目标 fail-closed：DSN 未指向演练库（非隔离目标）即拒绝（exit 3）。"""
    production_like = DSN.replace(f"/{SANDBOX_DB}", "/postgres")
    if production_like == DSN:
        pytest.skip("DSN 形如非隔离库名，无法构造反证目标")
    exit_code = cli.main(["status", "--build", "0" * 64, "--dsn", production_like])
    assert exit_code == cli.EXIT_TARGET
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"].startswith("拒绝")
