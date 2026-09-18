"""I2 全链路探针：CLI 入库 → 发布 → 检索 → 取证 → 文档级读 → coverage → 审计。

与各模块测试族的差别：**每一步都用上一步的真实产物**，不手工造 Store 行、不替身
被测层。因此它检验的是「链的不变量」，例如：

- 逐字性（硬闸①）：fetch 的 text 必须逐字出现在**源文件字节**里；
- 发布闭合：发布后不得残留 running job（否则恢复台账与已上线事实脱节）；
- 幂等：同清单重跑得同 build_id，重复发布不推进 generation；
- 撤销闭合：撤销后检索/取证/文档级读/覆盖/审计五处口径一致；
- 完整性：篡改权威单元后，所有读取路径都必须拒绝；
- 降级不可达：新库上请求 legacy 读路径必须 fail-closed。

每一步断言的都是**上一步的真实产物**（build_id、generation、句柄），失败即链路偏离。

环境：``i2-verify`` 守卫 env + ``CORPUS_I2_DSN`` → ``i2_sandbox_corpus``；仅写该库 corpus schema。
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

DSN = os.environ.get("CORPUS_I2_DSN", "")
if not DSN:
    pytest.skip("CORPUS_I2_DSN 未设置（非 I2 演练环境）", allow_module_level=True)

import psycopg  # noqa: E402

from plugins.corpus import cli  # noqa: E402
from plugins.corpus.audit import audit_corpus_chain  # noqa: E402
from plugins.corpus.preparation import read_pg  # noqa: E402
from plugins.corpus.preparation.contract import (  # noqa: E402
    Admission,
    AdmissionDecision,
    MaterialType,
    ReviewDecision,
    ReviewedDecision,
    sha256_of_bytes,
)
from plugins.corpus.preparation.repository import StoreError  # noqa: E402
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402
from plugins.corpus.service import CorpusService  # noqa: E402
from plugins.tools.corpus_fetch import corpus_fetch  # noqa: E402
from plugins.tools.corpus_search import corpus_search  # noqa: E402

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
ROOT = Path(__file__).resolve().parents[5]
FIXTURE = ROOT / "tests/fixtures/corpus_preparation/synthetic-company-report.md"
ARCHIVE_PARENT = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/tmp"
NOW = datetime(2026, 9, 18, 15, tzinfo=UTC)


def _source_text() -> str:
    """源文件字节 → 文本（逐字断言的唯一基准，不是解析产物）。"""
    return FIXTURE.read_text(encoding="utf-8")


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
def service(monkeypatch: pytest.MonkeyPatch) -> CorpusService:
    monkeypatch.setenv("CORPUS_READ_CHAIN", "new")
    monkeypatch.setattr("plugins.corpus.service.dsn", lambda: DSN)
    return CorpusService(DSN)


@pytest.fixture()
def chain(store: PgStore, capsys: pytest.CaptureFixture[str]) -> dict:
    """走完整条链的前半段：登记审核决定 → cli build → cli check → cli publish。"""
    decision = "chain-r1"
    store.put_reviewed_decision(
        ReviewedDecision(
            decision,
            sha256_of_bytes(FIXTURE.read_bytes()),
            "chain-test",
            NOW,
            ReviewDecision.ADMITTED,
            "synthetic whole-source admission",
        )
    )
    archive_root = ARCHIVE_PARENT / f"archive-chain-{uuid.uuid4().hex[:8]}"
    manifest = ARCHIVE_PARENT / f"chain-plan-{uuid.uuid4().hex[:8]}.json"
    archive_root.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "path": str(FIXTURE),
                        "domain_hint": "company",
                        "review_decision_ids": [decision],
                    }
                ],
                "archive_root": str(archive_root),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert cli.main(["build", "--manifest", str(manifest), "--dsn", DSN, "--owner", "chain"]) == (
        cli.EXIT_OK
    ), capsys.readouterr().out
    built = json.loads(capsys.readouterr().out)
    assert built["count"] == 1 and built["ok"] is True
    outcome = built["outcomes"][0]
    assert outcome["decision"] == "in_scope", outcome
    build_id = str(outcome["build_id"])

    assert cli.main(["check", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
    checked = json.loads(capsys.readouterr().out)
    assert checked["publishable"] is True and checked["publication"] is None

    assert cli.main(
        ["publish", "--build", build_id, "--operator", "chain-operator", "--dsn", DSN]
    ) == cli.EXIT_OK
    published = json.loads(capsys.readouterr().out)
    assert published["generation"] == 1 and published["active_build_id"] == build_id

    return {
        "build_id": build_id,
        "manifest": str(manifest),
        "archive_root": str(archive_root),
        "decision": decision,
        "check": checked,
        "publish": published,
        "source_bytes": _source_text(),
    }


# ── 回路判定：一次走完并核对每一步的真实产物 ──────────────────


def test_control_full_chain_reaches_reference_free_evidence(
    chain: dict, service: CorpusService, capsys: pytest.CaptureFixture[str]
) -> None:
    """阳性对照：整条链必须一次走通，且取证文本逐字来自源文件。"""
    build_id = chain["build_id"]

    # ② 检索：命中即句柄，且只服务活动版本
    hits = service.search("产能利用率", limit=5)
    assert hits, "检索无命中：链路断裂"
    hit = hits[0]
    assert hit.doc_id == f"cv2:{build_id}" and hit.locator.startswith("chunk:")

    # ③ 取证：逐字性——chunk.text 是所引单元 raw_text 的拼接，逐字性按**单元**成立
    #    （拼接用 "\n"，不复现源文件的空行分隔，故不可要求整个 chunk.text 是文件子串）。
    evidence = service.fetch_verbatim(hit.doc_id, hit.locator)
    assert evidence.units, "取证未返回任何权威单元"
    bad = [u.unit_id for u in evidence.units if u.raw_text not in chain["source_bytes"]]
    assert not bad, f"单元原文不在源文件中（非逐字）: {bad}"
    assert evidence.text == "\n".join(u.raw_text for u in evidence.units), (
        "chunk.text 不是所引单元 raw_text 的逐字拼接"
    )
    assert evidence.active is True

    # ④ 工具层必须经同一权威 Seam（不是另一条读路径）
    payload = json.loads(asyncio.run(corpus_search.ainvoke({"query": "产能利用率", "limit": 5})))
    assert payload["ok"] is True and payload["count"] >= 1
    tool_hit = payload["hits"][0]
    fetched = json.loads(
        asyncio.run(corpus_fetch.ainvoke({"doc_id": tool_hit["doc_id"], "locator": tool_hit["locator"]}))
    )
    assert fetched["text"] == evidence.text, "工具层与 service 层读出的不是同一份权威原文"

    # ⑤ 文档级读取：句柄语义 + 哈希核验
    #    注意：DocumentEvidence.text 同样是单元 raw_text 的 "\n" 拼接，**不复现源文件的空行**，
    #    故逐字性按「非空行」核对（每一行都必须原样出自源文件）。
    doc = read_pg.fetch_document(DSN, f"cv2:{build_id}", sandbox_db=SANDBOX_DB)
    assert doc.build_id == build_id
    lines = [line for line in doc.text.split("\n") if line.strip()]
    missing = [line for line in lines if line not in chain["source_bytes"]]
    assert not missing, f"文档级文本含非源文件行（非逐字）: {missing[:3]}"

    # ⑥ coverage：三轴 + 必带 ref（§7.3）
    coverage = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB, query_status="matched")
    for key in ("requested_scope_ref", "effective_scope_ref", "publication_snapshot_ref"):
        assert key in coverage, f"coverage 缺 §7.3 必带字段 {key}"
    assert coverage["counts"]["published"] == 1

    # ⑦ 审计：新链完整、无冲突
    with psycopg.connect(DSN, autocommit=True) as conn:
        report = audit_corpus_chain(conn)
    assert report["available"] is True
    assert report["conflicts"] == []


# ── 链不变量 1：数字/百分比跨「写侧归一化 → 检索归一化 → 取证」保持一致 ──


def test_chain_numeric_query_keeps_verbatim_numbers(
    chain: dict, service: CorpusService
) -> None:
    """百分比/小数点检索必须命中，且取证文本仍是源文件原样数字（归一化不得改正文）。"""
    for query, expected in (("23.5%", "23.5%"), ("82.3%", "82.3%"), ("42.50", "42.50")):
        hits = service.search(query, limit=5)
        assert hits, f"检索 {query!r} 无命中（写侧/查询侧归一化不一致）"
        units = [
            u
            for h in hits[:3]
            for u in service.fetch_verbatim(h.doc_id, h.locator).units
        ]
        assert any(expected in u.raw_text for u in units), (
            f"{query!r} 命中但取证单元中无原样数字 {expected!r}：{[u.raw_text[:50] for u in units]}"
        )
        assert all(u.raw_text in chain["source_bytes"] for u in units)


# ── 链不变量 2：发布后不得残留 running job（执行台账与上线事实一致）──


def test_chain_publish_leaves_no_running_job(chain: dict, store: PgStore) -> None:
    from plugins.corpus.preparation.contract import JobStage, JobState

    stages = (
        JobStage.REGISTERED,
        JobStage.ADMISSION_DECIDED,
        JobStage.PARSED,
        JobStage.CLEANED,
        JobStage.CHUNKED,
        JobStage.STAGED,
        JobStage.INDEXED,
        JobStage.VERIFIED,
        JobStage.PUBLISHED,
    )
    running = []
    for stage in stages:
        job = store.get_job(chain["build_id"], stage)
        if job is not None and job.state is JobState.RUNNING:
            running.append(stage.value)
    assert not running, f"发布后仍残留 running job：{running}"
    published = store.get_job(chain["build_id"], JobStage.PUBLISHED)
    assert published is not None and published.state is JobState.SUCCEEDED


# ── 链不变量 3：重跑幂等（同清单 → 同 build_id；重复发布 → 同 generation）──


def test_chain_rerun_is_idempotent(
    chain: dict, store: PgStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(
        ["build", "--manifest", chain["manifest"], "--dsn", DSN, "--owner", "chain-2"]
    ) == cli.EXIT_OK
    again = json.loads(capsys.readouterr().out)
    assert again["outcomes"][0]["build_id"] == chain["build_id"], "同清单重跑产生了新 build_id"

    assert cli.main(
        ["publish", "--build", chain["build_id"], "--operator", "chain-operator-2", "--dsn", DSN]
    ) == cli.EXIT_OK
    replay = json.loads(capsys.readouterr().out)
    assert replay["generation"] == 1, "重复发布推进了 generation"
    assert replay["activated_at"] == chain["publish"]["activated_at"]


# ── 链不变量 4：撤销后五处口径一致 ────────────────────────────


def test_chain_withdraw_signals_are_consistent(chain: dict, store: PgStore) -> None:
    """撤销后：取证/文档级读/覆盖率/审计四处信号必须一致，不得有空串冒充合法空文档。"""
    build_id = chain["build_id"]
    source_id = chain["publish"]["source_id"]
    chunk_id = CorpusService(DSN).search("产能利用率", limit=1)[0].chunk_id

    store.put_admission(
        Admission(
            decision_id="chain-exclude",
            source_id=source_id,
            material_type=MaterialType.PIPELINE_ARTIFACT,
            research_domain=None,
            decision=AdmissionDecision.EXCLUDED_BY_POLICY,
            policy_rev="v1-20260915",
        )
    )
    store.retire(source_id, "chain-exclude", NOW)

    assert CorpusService(DSN).search("产能利用率", limit=5) == [], "撤销后检索仍有候选"
    with pytest.raises(read_pg.WithdrawnError):
        read_pg.fetch_verbatim(DSN, f"cv2:{build_id}", f"chunk:{chunk_id}", sandbox_db=SANDBOX_DB)
    with pytest.raises(read_pg.WithdrawnError):
        read_pg.fetch_document(DSN, f"cv2:{build_id}", sandbox_db=SANDBOX_DB)

    coverage = read_pg.coverage_snapshot(DSN, sandbox_db=SANDBOX_DB, query_status="no_match")
    assert coverage["counts"]["published"] == 0
    assert "withdrawn_sources" in coverage["reason_codes"]

    with psycopg.connect(DSN, autocommit=True) as conn:
        from plugins.corpus.audit import audit_corpus_chain

        assert audit_corpus_chain(conn)["conflicts"] == []


# ── 链不变量 5：篡改权威单元 → 所有读取路径拒绝 ─────────────────


def test_chain_tampered_authority_is_rejected_everywhere(chain: dict) -> None:
    build_id = chain["build_id"]
    chunk_id = CorpusService(DSN).search("产能利用率", limit=1)[0].chunk_id

    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE corpus.corpus_units SET raw_text = raw_text || '（篡改）' WHERE build_id = %s",
            (build_id,),
        )
        assert cur.rowcount >= 1

    with pytest.raises(read_pg.IntegrityError):
        read_pg.fetch_verbatim(DSN, f"cv2:{build_id}", f"chunk:{chunk_id}", sandbox_db=SANDBOX_DB)
    with pytest.raises(read_pg.IntegrityError):
        read_pg.fetch_document(DSN, f"cv2:{build_id}", sandbox_db=SANDBOX_DB)


# ── 链不变量 6：新库上 legacy 降级不可达 ─────────────────────


def test_chain_legacy_downgrade_is_unreachable_on_new_db(
    chain: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORPUS_READ_CHAIN", "legacy")
    svc = CorpusService(DSN)
    with pytest.raises(StoreError, match="legacy|不可达|拒绝"):
        svc.search("产能利用率", limit=5)


# ── 链不变量 7：跨发布句柄稳定（search 只给新，旧句柄仍得旧正文）──


def test_chain_cross_publish_handle_stability(
    chain: dict, service: CorpusService, capsys: pytest.CaptureFixture[str]
) -> None:
    """追加一份不同来源并发布，旧来源的句柄必须仍指向原 build。"""
    old_build = chain["build_id"]
    old_hit = service.search("产能利用率", limit=1)[0]
    old_text = service.fetch_verbatim(old_hit.doc_id, old_hit.locator).text

    # 第二份来源用「同一夹具的改写版」：字节不同 → source_id 不同，但内容结构合法可发布。
    alt = Path(chain["archive_root"]).parent / f"chain-alt-{uuid.uuid4().hex[:8]}.md"
    alt.write_text(
        chain["source_bytes"].replace("星尘新材料", "云帆新材"),
        encoding="utf-8",
    )
    store = PgStore(DSN, sandbox_db=SANDBOX_DB)
    try:
        from plugins.corpus.preparation.contract import ReviewDecision as RD
        from plugins.corpus.preparation.contract import ReviewedDecision as RevD

        decision = "chain-r2"
        store.put_reviewed_decision(
            RevD(
                decision,
                sha256_of_bytes(alt.read_bytes()),
                "chain-test",
                NOW,
                RD.ADMITTED,
                "synthetic alt admission",
            )
        )
    finally:
        store.close()
    manifest = Path(chain["archive_root"]).parent / f"chain-plan2-{uuid.uuid4().hex[:8]}.json"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {"path": str(alt), "domain_hint": "company", "review_decision_ids": ["chain-r2"]}
                ],
                "archive_root": chain["archive_root"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert cli.main(
        ["build", "--manifest", str(manifest), "--dsn", DSN, "--owner", "chain-3"]
    ) == cli.EXIT_OK
    new_build = str(json.loads(capsys.readouterr().out)["outcomes"][0]["build_id"])
    assert cli.main(
        ["publish", "--build", new_build, "--operator", "chain-op-3", "--dsn", DSN]
    ) == cli.EXIT_OK
    capsys.readouterr()

    # 旧来源（不同 source_id）句柄仍稳定；其 document_text 与 build_id 自洽
    again = service.fetch_verbatim(f"cv2:{old_build}", old_hit.locator)
    assert again.text == old_text, "跨发布后旧句柄的正文被静默切换"
    doc = read_pg.fetch_document(DSN, f"cv2:{old_build}", sandbox_db=SANDBOX_DB)
    assert doc.build_id == old_build
    assert old_text in doc.text


# ── 链不变量 8：命中与覆盖元数据取自同一快照 ────────────────────


def test_chain_hits_and_coverage_share_one_snapshot(chain: dict) -> None:
    hits, coverage = read_pg.search_with_coverage(DSN, "产能利用率", sandbox_db=SANDBOX_DB)
    assert hits, "同快照组合读取未命中"
    assert coverage["query_status"] == "matched"
    assert coverage["counts"]["published"] >= 1, (
        f"命中与覆盖元数据不同源：有命中却报告 published={coverage['counts']['published']}"
    )
    assert coverage["publication_snapshot_ref"]


# ── 出口/可用性探针（失败 = 改进项；本类不声称契约被违反）──────────


def _build_gapped_docx(store: PgStore, capsys: pytest.CaptureFixture[str]) -> str:
    """用受批 DOCX 夹具（含 cell 图 → ``unreadable_element``）走完 build，返回 build_id。"""
    docx = ROOT / "tests/fixtures/corpus_preparation/synthetic-company-report.docx"
    store.put_reviewed_decision(
        ReviewedDecision(
            "chain-docx",
            sha256_of_bytes(docx.read_bytes()),
            "chain-test",
            NOW,
            ReviewDecision.ADMITTED,
            "synthetic docx admission",
        )
    )
    archive_root = ARCHIVE_PARENT / f"archive-chain-docx-{uuid.uuid4().hex[:8]}"
    archive_root.mkdir(parents=True, exist_ok=True)
    manifest = ARCHIVE_PARENT / f"chain-docx-{uuid.uuid4().hex[:8]}.json"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "path": str(docx),
                        "domain_hint": "company",
                        "review_decision_ids": ["chain-docx"],
                    }
                ],
                "archive_root": str(archive_root),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert cli.main(
        ["build", "--manifest", str(manifest), "--dsn", DSN, "--owner", "chain-docx"]
    ) == cli.EXIT_OK, capsys.readouterr().out
    return str(json.loads(capsys.readouterr().out)["outcomes"][0]["build_id"])


def test_gapped_build_cannot_publish_and_stays_rejected_on_retry(
    store: PgStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """§7.3 的 ``scoped`` 前提是「子集内无未决必需区域」，允许发布已获准子集；
    实测含缺口的 build 在**任何**操作下都不可发布（缺口区域 ``ordinal=None``，
    不参与 scope 判定 → 无法证明其在请求范围之外），因此 ``scoped`` 在实现上不可达。"""
    build_id = _build_gapped_docx(store, capsys)
    for attempt in (1, 2):
        code = cli.main(
            ["publish", "--build", build_id, "--operator", f"chain-docx-{attempt}", "--dsn", DSN]
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == cli.EXIT_GATE, f"第 {attempt} 次 publish 未被拒绝：{payload}"
        assert "gap_regions" in str(payload.get("error")), payload


def test_gap_rejection_exposes_machine_readable_gaps_in_check(
    store: PgStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """``check`` 拒绝含缺口的 build 时，必须给出机器可读的缺口清单（而非仅 error 文本）。"""
    build_id = _build_gapped_docx(store, capsys)
    code = cli.main(["check", "--build", build_id, "--dsn", DSN])
    payload = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_GATE, f"含缺口 build 的 check 未被拒绝：{payload}"
    assert payload.get("gaps"), (
        "check 拒绝时未给出机器可读的缺口清单（只有 error 文本）："
        f"keys={sorted(payload)}；error={str(payload.get('error'))[:120]!r}"
    )


def test_status_shows_gaps_per_cli_contract(
    store: PgStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """架构 §9 CLI 表：``corpus-status`` 须显示「阶段、失败、**缺口**与可执行恢复路径」。"""
    build_id = _build_gapped_docx(store, capsys)
    assert cli.main(["status", "--build", build_id, "--dsn", DSN]) == cli.EXIT_OK
    status = json.loads(capsys.readouterr().out)
    assert status.get("gaps"), (
        "status 未显示缺口（架构 §9：corpus-status 须显示阶段、失败、缺口与可执行恢复路径）："
        f"keys={sorted(status)}"
    )

