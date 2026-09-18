"""缺口裁决（RM-FC-0 / 架构 §7.3）常驻回归：分级、坐标、scope 归属与 CLI 可见性。

背景（I2 全链路独立复核 F1/F2）：此前**任何**缺口都恒阻断发布、缺口无坐标、且
``check``/``status`` 不暴露机器可读缺口，使 §7.3 的 ``scoped`` 在实现上不可达。
本文件把裁定后的契约固化为回归：

- 词表唯一来源：``gaps.GAP_CODE_STATUS`` / ``DEFAULT_GAP_DISPOSITION`` /
  ``GAP_CODE_REMEDY`` 三表同键集；默认分级与架构 §7.3 表逐项一致（漂移即红）。
- 缺口身份 ``issue:<code>:<location>`` 可解析、可坐标化；不可解析/词表外一律
  ``blocking``（fail-closed）。
- 生命周期：可证落在获批 ``char:`` 区间之外 → ``out_of_scope``（不阻断）；
  部分重叠或无坐标 → 回落默认分级（不得因「坐标缺失」而放行）。
- 台账不可回退为静默丢弃：``acknowledged`` 缺口放行后仍留在 ``quality_report``、
  ``check``/``status`` 的 ``gaps`` 与 ``coverage.reason_codes``，并在 PUBLISHED
  job 检查点留下记录人与依据。

PG 用例（``TestI2GapCli``）需 ``CORPUS_I2_DSN``（i2-verify 守卫 env）；其它用例
零模型、零网络、无 PG。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pymupdf
import pytest

from plugins.corpus.preparation.admission import POLICY_REV_V1, AdmissionPolicy
from plugins.corpus.preparation.contract import (
    Build,
    JobStage,
    JobState,
    LeaseConfig,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    source_id_from_bytes,
)
from plugins.corpus.preparation.engine import (
    EngineError,
    PlanEntry,
    execute_builds,
    gap_records_of,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.gaps import (
    DEFAULT_GAP_DISPOSITION,
    GAP_CODE_REMEDY,
    GAP_CODE_STATUS,
    GAP_POLICY_REV,
    GapCoordinateKind,
    GapDisposition,
    GapLifecycle,
    blocking_gaps,
    evaluate_against_scope,
    gap_key,
    gap_records,
    gap_summary,
    parse_gap_key,
    parse_gap_location,
    recovery_paths,
)
from plugins.corpus.preparation.repository import MemoryStore, StoreError

DSN = os.environ.get("CORPUS_I2_DSN", "")
SANDBOX_DB = "i2_sandbox_corpus"
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/corpus_preparation"
DOCX_FIXTURE = FIXTURES / "synthetic-company-report.docx"
MD_FIXTURE = FIXTURES / "synthetic-company-report.md"
TMP_ROOT = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/tmp"
NOW = datetime(2026, 9, 18, 16, tzinfo=UTC)
POLICY = AdmissionPolicy(POLICY_REV_V1, tuple(ResearchDomain))
LEASE = LeaseConfig(300, 60, 600, 3)
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


# ── 1. 词表与默认分级（架构 §7.3 表逐项锁定） ──────────────────


def test_gap_code_tables_are_one_vocabulary() -> None:
    """码表/分级表/恢复路径表必须同键集——三张表漂移即红。"""
    codes = set(GAP_CODE_STATUS)
    assert codes == set(DEFAULT_GAP_DISPOSITION) == set(GAP_CODE_REMEDY), (
        "缺口词表漂移："
        f"status={sorted(set(GAP_CODE_STATUS) ^ set(DEFAULT_GAP_DISPOSITION))} "
        f"remedy={sorted(set(GAP_CODE_STATUS) ^ set(GAP_CODE_REMEDY))}"
    )


def test_default_grading_matches_architecture_7_3_table() -> None:
    """默认分级逐项与架构 §7.3 表一致（含「未丢失正文」判据）。"""
    acknowledged = {
        "empty_page",
        "image_region_small",
        "unterminated_code_fence",
    }
    blocking = {
        "image_only_page",
        "image_region_unreadable",
        "table_extraction_failed",
        "table_lines_without_extraction",
        "unreadable_element",
        "unknown_body_element",
    }
    assert set(DEFAULT_GAP_DISPOSITION) == acknowledged | blocking
    for code in acknowledged:
        assert DEFAULT_GAP_DISPOSITION[code] is GapDisposition.ACKNOWLEDGED, code
    for code in blocking:
        assert DEFAULT_GAP_DISPOSITION[code] is GapDisposition.BLOCKING, code
    # review.md 点名的两类：空白页（极高常见度）必须可放行；表格抽取失败仍阻断。
    assert DEFAULT_GAP_DISPOSITION["empty_page"] is GapDisposition.ACKNOWLEDGED
    assert DEFAULT_GAP_DISPOSITION["table_extraction_failed"] is GapDisposition.BLOCKING


def test_gap_key_round_trip_and_unparsable_key_fails_closed() -> None:
    key = gap_key("empty_page", "page:4")
    assert key == "issue:empty_page:page:4"
    assert parse_gap_key(key) == ("empty_page", "page:4")
    # DOCX 位置自带 "/" 与 ":"：仍可无损解回
    docx_key = gap_key("unreadable_element", "body[5]:tbl[0]/row[0]/cell[1]")
    assert parse_gap_key(docx_key) == (
        "unreadable_element",
        "body[5]:tbl[0]/row[0]/cell[1]",
    )
    for bad in ("", "empty_page:page:1", "issue:empty_page", "issue::page:1", 12):
        assert parse_gap_key(bad) is None  # type: ignore[arg-type]
    # 不可解析 / 词表外一律 blocking（看不见的缺口比误阻断更危险）
    for record in gap_records(["issue:empty_page", "issue:brand_new_code:page:1"]):
        assert record.lifecycle is GapLifecycle.BLOCKING, record
        assert record.disposition is GapDisposition.BLOCKING, record
        assert record.basis.startswith("unclassified_code:") or record.code == "brand_new_code"


def test_gap_locations_become_structured_coordinates() -> None:
    page = parse_gap_location("page:12")
    assert (page.kind, page.page) == (GapCoordinateKind.PAGE, 12)
    char = parse_gap_location("char:100-140")
    assert (char.kind, char.char_start, char.char_end) == (GapCoordinateKind.CHAR, 100, 140)
    open_char = parse_gap_location("char:100-")
    assert (open_char.kind, open_char.char_start, open_char.char_end) == (
        GapCoordinateKind.CHAR,
        100,
        None,
    )
    element = parse_gap_location("body[5]:tbl[0]/row[0]/cell[1]")
    assert element.kind is GapCoordinateKind.ELEMENT
    assert element.element == "body[5]:tbl[0]/row[0]/cell[1]"
    # 无法判定 → 显式 unlocatable（不静默假设）
    assert parse_gap_location("page:not-a-number").kind is GapCoordinateKind.UNLOCATABLE


# ── 2. scope 归属：可证范围外不阻断，不可证不回落放行 ──────────


def _lifecycle(key: str, scope: tuple[tuple[int, int], ...]) -> GapLifecycle:
    evaluated = evaluate_against_scope(gap_records([key]), scope)
    return evaluated[0].lifecycle


def test_provably_out_of_scope_gap_does_not_block() -> None:
    # 围栏缺口在 char:600-，获批范围只到 200：缺口整段在批准区间之外 → out_of_scope
    key = gap_key("unterminated_code_fence", "char:600-")
    assert _lifecycle(key, ((0, 200),)) is GapLifecycle.OUT_OF_SCOPE
    # 完全落在批准区间内 → 保持默认分级（acknowledged）
    inside = gap_key("unterminated_code_fence", "char:100-180")
    assert _lifecycle(inside, ((0, 200),)) is GapLifecycle.ACKNOWLEDGED
    # 部分重叠 → 不可证范围外 → 回落默认分级（宁可保守）
    overlap = gap_key("unterminated_code_fence", "char:150-260")
    assert _lifecycle(overlap, ((0, 200),)) is GapLifecycle.ACKNOWLEDGED


def test_unlocatable_gap_keeps_default_disposition() -> None:
    # 页坐标/元素坐标没有 char 区间：scope 无法证明其在范围之外 → 不因此放行
    for key in (
        gap_key("unreadable_element", "body[5]:tbl[0]/row[0]/cell[1]"),
        gap_key("image_only_page", "page:3"),
    ):
        assert _lifecycle(key, ((0, 200),)) is GapLifecycle.BLOCKING, key


# ── 3. 发布门：acknowledged 放行且留痕，blocking 仍拒绝 ────────


def _cli_json(capsys: pytest.CaptureFixture[str]) -> dict:
    """读取 CLI 的 stdout 并解析 JSON 载荷。

    **不得**直接 ``json.loads(stdout)``：第三方库（实测 pymupdf）会在进程首次调用时向
    stdout 打一次性提示行（``Consider using the pymupdf_layout package…``），使同一用例在
    「整文件运行」与「单独运行 / 被 -k 选中」下得到不同结果（顺序依赖的假红）。这里从第一个
    ``{`` 起解析，与任何前置提示行解耦。
    """
    out = capsys.readouterr().out
    start = out.find("{")
    assert start >= 0, f"CLI 未输出 JSON 载荷: {out[:200]!r}"
    return json.loads(out[start:])


def _write_text_page_plus_blank_page(path: Path) -> None:
    """一页正文 + 一页空白（分页/封底）——真实研报最常见的缺口形态。"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Readable title", fontsize=11)
    doc.new_page()
    doc.save(str(path))
    doc.close()


def _memory_reviewed(store: MemoryStore, path: Path, decision: str) -> str:
    sid = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(
        ReviewedDecision(decision, sid, "reviewer", NOW, ReviewDecision.ADMITTED, "approval")
    )
    return sid


@pytest.fixture()
def workdir() -> Path:
    """仓库内的工作目录（i2-verify 守卫 env 只放行仓库内临时路径，/tmp 被拒）。"""
    path = TMP_ROOT / f"gap-case-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_empty_page_gap_is_acknowledged_and_publishable_with_record(
    workdir: Path,
) -> None:
    """含空白页的 PDF 按其默认分级可发布；缺口仍可见且 PUBLISHED 检查点留痕。"""
    path = workdir / "cover.pdf"
    _write_text_page_plus_blank_page(path)
    store = MemoryStore(clock=lambda: NOW)
    _memory_reviewed(store, path, "r1")
    plan = plan_builds(
        [PlanEntry(str(path), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("r1",))],
        policy=POLICY,
    )
    outcome = execute_builds(
        store,
        plan,
        policy=POLICY,
        archive_root=workdir / "archive",
        owner_id="gap",
        now=NOW,
        lease=LEASE,
    ).outcomes[0]
    assert outcome.build is not None
    build_id = outcome.build.build_id

    records = gap_records_of(outcome.build)
    assert [r.code for r in records] == ["empty_page"], records
    assert records[0].lifecycle is GapLifecycle.ACKNOWLEDGED
    assert records[0].coordinates.page == 2
    # 缺口仍在台账里（不得回退为静默丢弃）
    assert "issue:empty_page:page:2" in json.loads(outcome.build.quality_report)["gap_regions"]

    publication = publish_build(store, build_id, activated_at=NOW, operator="alice")
    assert publication.active_build_id == build_id
    checkpoint = json.loads(store.get_job(build_id, JobStage.PUBLISHED).checkpoint or "{}")
    assert checkpoint["operator"] == "alice"  # 记录人 = 发布操作者
    assert checkpoint["gap_policy_rev"] == GAP_POLICY_REV  # 依据 = 默认分级表版本
    assert checkpoint["acknowledged_gaps"] == ["issue:empty_page:page:2"]


class _TamperStore(MemoryStore):
    """put_build 直写（绕过幂等冲突检查）——仅用于注入指定缺口台账。"""

    def put_build(self, build: Build) -> None:
        self._builds[build.build_id] = build


def test_blocking_gap_still_rejected_with_machine_readable_reason(workdir: Path) -> None:
    """表格抽取失败（默认 blocking）：仍被拒，且拒绝原因机读可路由。"""
    path = workdir / "report.md"
    path.write_text("# 研报\n\n正文。\n", encoding="utf-8")
    store = _TamperStore(clock=lambda: NOW)
    _memory_reviewed(store, path, "r1")
    plan = plan_builds(
        [PlanEntry(str(path), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("r1",))],
        policy=POLICY,
    )
    build = (
        execute_builds(
            store,
            plan,
            policy=POLICY,
            archive_root=workdir / "archive",
            owner_id="gap",
            now=NOW,
            lease=LEASE,
        )
        .outcomes[0]
        .build
    )
    assert build is not None
    build_id = build.build_id
    # PARSED/CHUNKED 已由引擎置 SUCCEEDED：只替换质量台账，隔离出缺口这一道门。
    store.put_build(
        Build(
            build_id=build_id,
            source_id=build.source_id,
            decision_id=build.decision_id,
            parse_rev=build.parse_rev,
            clean_rev=build.clean_rev,
            chunk_rev=build.chunk_rev,
            index_rev=build.index_rev,
            scope_ref=build.scope_ref,
            quality_report=json.dumps(
                {
                    "gap_regions": ["issue:table_extraction_failed:page:2"],
                    "oversized_chunks": [],
                }
            ),
        )
    )
    with pytest.raises(EngineError) as excinfo:
        publish_build(store, build_id, activated_at=NOW)
    message = str(excinfo.value)
    assert "gap_regions" in message, message
    assert "table_extraction_failed" in message, message
    assert store.get_publication(build.source_id) is None


# ── 4. 摘要/恢复路径（check/status 的机读字段） ────────────────


def test_summary_and_recovery_paths_are_actionable() -> None:
    records = evaluate_against_scope(
        gap_records(
            [
                gap_key("empty_page", "page:4"),
                gap_key("image_only_page", "page:3"),
                gap_key("unterminated_code_fence", "char:600-"),
            ]
        ),
        ((0, 200),),
    )
    summary = gap_summary(records)
    assert (summary["total"], summary["blocking"], summary["acknowledged"]) == (3, 1, 1)
    assert summary["out_of_scope"] == 1
    assert summary["policy_rev"] == GAP_POLICY_REV
    assert len(blocking_gaps(records)) == 1
    paths = recovery_paths(records)
    assert [p["code"] for p in paths] == ["empty_page", "image_only_page"]
    blocking_path = next(p for p in paths if p["code"] == "image_only_page")
    assert "OCR" in str(blocking_path["action"]) and "command" in blocking_path
    # 范围外的缺口不需要恢复动作（本就不在请求范围内）
    assert all(p["code"] != "unterminated_code_fence" for p in paths)


# ── 5. 端到端 CLI：缺口机读可见 + coverage 如实（真库） ─────────


@pytest.mark.skipif(not DSN, reason="CORPUS_I2_DSN 未设置（非 I2 演练环境）")
class TestI2GapCli:
    """i2-verify 守卫 env：``check``/``status``/``plan`` 与 coverage 的缺口口径。"""

    @pytest.fixture(autouse=True)
    def _clean_tables(self) -> None:
        import psycopg

        with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            database = cur.fetchone()[0]
            if database != SANDBOX_DB:
                raise StoreError(f"拒绝清理：current_database={database!r} ≠ {SANDBOX_DB!r}")
            cur.execute("SELECT datname FROM pg_database WHERE datallowconn")
            if "apodex" in {r[0] for r in cur.fetchall()}:
                raise StoreError("拒绝清理：目标实例含 apodex 库")
            cur.execute(f"TRUNCATE {', '.join(f'corpus.{t}' for t in TABLES)}")
        TMP_ROOT.mkdir(parents=True, exist_ok=True)

    def _build_via_cli(self, source: Path, capsys: pytest.CaptureFixture[str], *, tag: str) -> str:
        from plugins.corpus import cli
        from plugins.corpus.preparation.contract import sha256_of_bytes
        from plugins.corpus.preparation.repository_pg import PgStore

        store = PgStore(DSN, sandbox_db=SANDBOX_DB)
        try:
            store.put_reviewed_decision(
                ReviewedDecision(
                    "gap-r1",
                    sha256_of_bytes(source.read_bytes()),
                    "gap-test",
                    NOW,
                    ReviewDecision.ADMITTED,
                    "synthetic admission",
                )
            )
        finally:
            store.close()
        archive_root = TMP_ROOT / f"archive-gap-{tag}-{uuid.uuid4().hex[:8]}"
        archive_root.mkdir(parents=True, exist_ok=True)
        manifest = TMP_ROOT / f"gap-plan-{tag}-{uuid.uuid4().hex[:8]}.json"
        manifest.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "path": str(source),
                            "domain_hint": "company",
                            "review_decision_ids": ["gap-r1"],
                        }
                    ],
                    "archive_root": str(archive_root),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        assert (
            cli.main(["build", "--manifest", str(manifest), "--dsn", DSN, "--owner", "gap-cli"])
            == cli.EXIT_OK
        ), capsys.readouterr().out
        payload = _cli_json(capsys)
        build_id = payload["outcomes"][0]["build_id"]
        assert build_id, payload
        return str(build_id)

    def test_check_and_status_expose_structured_gaps(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from plugins.corpus import cli

        build_id = self._build_via_cli(DOCX_FIXTURE, capsys, tag="docx")

        assert cli.main(["check", "--build", build_id, "--dsn", DSN]) == cli.EXIT_GATE
        check = _cli_json(capsys)
        assert check["publishable"] is False
        assert check["gaps"], "check 拒绝时必须给出结构化缺口"
        first = check["gaps"][0]
        assert first["code"] == "unreadable_element"
        assert first["lifecycle"] == "blocking"
        assert first["disposition"] == "blocking"
        assert first["coordinates"]["kind"] == "element"
        assert first["status"] == "review_required"
        assert check["gap_summary"]["blocking"] == len(check["gaps"])
        assert check["recovery"] and check["recovery"][0]["action"]
        assert "gap_regions" in check["error"]  # 人类可读文案仍保留

        assert cli.main(["status", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
        status = _cli_json(capsys)
        assert status["gaps"] == check["gaps"]
        assert status["gap_summary"]["blocking"] >= 1
        assert status["recovery"], "status 必须给出可执行恢复路径"
        assert "缺口" in status["next"]

    def test_acknowledged_gap_publishes_and_coverage_is_scoped(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """含空白页的 PDF：可发布；缺口保持可见；coverage 如实降级为 scoped。"""
        from plugins.corpus import cli
        from plugins.corpus.preparation import read_pg

        source = TMP_ROOT / f"gap-cover-{uuid.uuid4().hex[:8]}.pdf"
        _write_text_page_plus_blank_page(source)
        build_id = self._build_via_cli(source, capsys, tag="pdf")

        assert cli.main(["check", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
        check = _cli_json(capsys)
        assert check["publishable"] is True
        assert [g["code"] for g in check["gaps"]] == ["empty_page"]
        assert check["gaps"][0]["lifecycle"] == "acknowledged"
        assert check["gap_summary"]["blocking"] == 0

        assert (
            cli.main(["publish", "--build", build_id, "--operator", "alice", "--dsn", DSN])
            == cli.EXIT_OK
        )
        published = _cli_json(capsys)
        assert published["generation"] == 1
        assert published["record"]["acknowledged_gaps"] == ["issue:empty_page:page:2"]
        assert published["record"]["gap_policy_rev"] == GAP_POLICY_REV

        assert cli.main(["status", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
        status = _cli_json(capsys)
        assert status["gaps"] and status["gap_summary"]["acknowledged"] == 1
        assert "scoped" in status["next"]

        coverage = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB, query_status="matched")
        assert coverage["processing"] == "scoped", coverage
        assert "gap_regions_present" in coverage["reason_codes"]
        assert coverage["counts"]["published_with_gaps"] == 1

    def test_plan_precheck_shares_the_same_verdict(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """plan 预检与 check 判定同口径：阻断类材料预判不可发布，干净材料预判可发布。"""
        from plugins.corpus import cli

        manifest = TMP_ROOT / f"gap-precheck-{uuid.uuid4().hex[:8]}.json"
        manifest.write_text(
            json.dumps(
                {
                    "sources": [
                        {"path": str(MD_FIXTURE), "domain_hint": "company"},
                        {"path": str(DOCX_FIXTURE), "domain_hint": "company"},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        assert cli.main(["plan", "--manifest", str(manifest)]) == cli.EXIT_OK
        plan = _cli_json(capsys)
        by_name = {Path(e["path"]).name: e["precheck"] for e in plan["entries"]}
        clean = by_name[MD_FIXTURE.name]
        gapped = by_name[DOCX_FIXTURE.name]
        assert clean["publishable_prejudgement"] is True
        assert clean["gaps"] == []
        assert gapped["publishable_prejudgement"] is False
        assert [g["code"] for g in gapped["gaps"]] == ["unreadable_element"]
        assert gapped["recovery"], "预检也必须给出可执行恢复路径"
        assert plan["precheck_summary"]["publishable"] == 1
        assert plan["precheck_summary"]["not_publishable"] == 1

        # 同口径核对：同一份 DOCX 走真链，check 的阻断集合 == 预检的阻断集合
        build_id = self._build_via_cli(DOCX_FIXTURE, capsys, tag="precheck")
        assert cli.main(["check", "--build", build_id, "--dsn", DSN]) == cli.EXIT_GATE
        check = _cli_json(capsys)
        assert {g["key"] for g in check["gaps"]} == {g["key"] for g in gapped["gaps"]}

    def test_document_text_is_unit_join_not_byte_restore(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """F3/RM-FC-5：文档级 ``text`` 是单元 ``\\n`` 拼接，不复现源文件空行。"""
        from plugins.corpus import cli
        from plugins.corpus.preparation import read_pg

        source = TMP_ROOT / f"gap-join-{uuid.uuid4().hex[:8]}.md"
        source.write_text("# 标题\n\n第一段。\n\n第二段。\n", encoding="utf-8")
        build_id = self._build_via_cli(source, capsys, tag="join")
        assert (
            cli.main(["publish", "--build", build_id, "--operator", "bob", "--dsn", DSN])
            == cli.EXIT_OK
        )
        capsys.readouterr()

        document = read_pg.fetch_document(DSN, f"cv2:{build_id}", sandbox_db=SANDBOX_DB)
        assert document.build_id == build_id
        # 逐字性按单元成立；拼接结果不等于源文件切片（空行分隔丢失）
        raw = source.read_text(encoding="utf-8")
        assert document.text != raw
        assert "\n\n" not in document.text
        for line in (line for line in document.text.split("\n") if line.strip()):
            assert line in raw
