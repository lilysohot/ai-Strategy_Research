"""D2 验收：claim 抽取。

覆盖：分级（省 LLM 调用）、LLM 输出容错、字段清洗、**可溯源（locator）**、
端到端落库与查询、幂等重跑、单块失败不中断。

P1 新增（d2-claims-design §3.1/§3.2/§5.1）：文档领域分类 ``doc_kind`` 与插槽选择、
``value_num`` / ``unit`` / ``as_of`` 三列事实列的派生与落库、macro 插槽的三态拆分
契约、误判纠正入口（``set-doc-kind``）。

另有一组「钱不能白花」的验收（见文件末尾）：**逐块落库**、**中断/失败后已完成块
不丢**、**重跑跳过已标记的块（含抽出 0 条的）**、**换模型/改 prompt 自动失效重抽
并整块替换**、**连续失败熔断**、**死信不再重试**。

隔离方式与 ``test_corpus_a1_ingest_search.py`` 一致：临时 schema，PG 不可用则 skip。
LLM 全程**注入假实现**，不发真实请求。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from decimal import Decimal
from urllib.parse import quote

import psycopg
import pytest

import plugins.corpus.claims as claims_mod
from plugins.corpus.claims import (
    DOC_KINDS,
    TABLE_APPENDIX,
    BlockView,
    Claim,
    apply_as_of_fallback,
    apply_doc_ticker,
    build_prompt,
    claims_from_payload,
    classify_doc_kind,
    document_ticker,
    extract_from_block,
    has_signal,
    is_flat_table,
    max_output_tokens,
    normalize_metric,
    parse_as_of,
    parse_claims_json,
    parse_value,
    triage_blocks,
    unit_scale,
    with_retry,
)
from plugins.corpus.service import CorpusService, _dedup_claims, dsn

FAKE_RESPONSE = json.dumps(
    [
        {
            "claim": "贵州茅台 2026H1 营业收入约 1741 亿元",
            "kind": "fact",
            "tickers": ["600519.SH"],
            "metric": "营业收入",
            "value": "1741亿元",
            "period": "2026H1",
            "confidence": 0.9,
        },
        {
            "claim": "目标价 1888 元，维持增持评级",
            "kind": "forecast",
            "tickers": ["600519.SH", ""],
            "metric": "目标价",
            "value": "1888元",
            "period": None,
            "confidence": 1.7,
        },
    ],
    ensure_ascii=False,
)


def _scratch_url(admin: str, schema: str) -> str:
    options = quote(f"-c search_path={schema},public")
    sep = "&" if "?" in admin else "?"
    return f"{admin}{sep}options={options}"


# ── 分级 ─────────────────────────────────────────────────────────
def test_triage_keeps_blocks_with_numbers() -> None:
    blocks = [BlockView(1, "1", "营业收入 1741 亿元，同比增长 1.3%")]
    candidates, skipped = triage_blocks(blocks)
    assert len(candidates) == 1 and skipped == 0


def test_triage_skips_noise_and_numberless_blocks() -> None:
    blocks = [
        BlockView(1, "1", "免责声明：本报告未经书面许可不得转载。"),
        BlockView(2, "2", "这是一段没有数字的定性描述。"),
    ]
    candidates, skipped = triage_blocks(blocks)
    assert candidates == [] and skipped == 2
    assert has_signal("目标价 88 元") is True


# ── LLM 输出容错 ────────────────────────────────────────────────
def test_parse_claims_json_tolerates_fences_and_prose() -> None:
    raw = '好的，结果如下：\n```json\n[{"claim": "营收 1741 亿元"}]\n```\n以上是结果。'
    parsed = parse_claims_json(raw)
    assert len(parsed) == 1 and "1741" in parsed[0]["claim"]


def test_parse_claims_json_returns_empty_on_garbage() -> None:
    assert parse_claims_json("我不是 JSON") == []
    assert parse_claims_json("") == []


def test_parse_claims_json_unwraps_object() -> None:
    assert len(parse_claims_json('{"claims": [{"claim": "营收增长"}]}')) == 1


# ── 字段清洗 ────────────────────────────────────────────────────
def test_claims_from_payload_cleans_fields() -> None:
    claims = claims_from_payload(
        [
            {
                "claim": "目标价 1888 元",
                "kind": "瞎写的",
                "tickers": ["600519.SH", ""],
                "confidence": 1.7,
            },
            {"claim": "太短"},  # 长度不足，丢弃
            {"kind": "fact"},  # 无 claim 文本，丢弃
        ],
        doc_id="2026-09-09_abcdef12",
        seq=3,
        locator="3",
    )

    assert len(claims) == 1
    claim = claims[0]
    assert claim.kind == "forecast", "非法 kind 应回退推断（含「目标价」⇒ forecast）"
    assert claim.tickers == ("600519.SH",), "空 ticker 应被过滤"
    assert claim.confidence == 1.0, "confidence 应被夹到 [0,1]"
    assert claim.locator == "3" and claim.seq == 3


def test_extract_from_block_keeps_locator_for_traceability() -> None:
    """claim 必须能回到原文 —— 这是硬闸①的口径。"""
    claims = extract_from_block(
        BlockView(7, "7", "营业收入 1741 亿元"),
        doc_id="2026-09-09_abcdef12",
        llm=lambda prompt: FAKE_RESPONSE,
    )
    assert claims and all(c.locator == "7" for c in claims)
    assert all(c.doc_id == "2026-09-09_abcdef12" for c in claims)


# ── 端到端（独立 schema） ──────────────────────────────────────
def test_end_to_end_extract_and_query(e2e_svc) -> None:
    """直插 documents/blocks：I2-7 写路径已代理引擎链路，ingest_dir 走守卫。"""
    svc = e2e_svc

    stats = svc.extract_legacy_claims(llm=lambda prompt: FAKE_RESPONSE)

    assert stats.failed == 0, stats.as_dict()
    assert stats.claims == 2, stats.as_dict()
    assert stats.skipped_no_signal >= 0

    # ① 可按标的查（D3 挖掘 / D4 共识度的入口）
    by_ticker = svc.legacy_claims_of(ticker="600519.SH")
    assert len(by_ticker) == 2
    assert all("600519.SH" in row["tickers"] for row in by_ticker)

    # ② 可按类型查（fact / forecast）
    assert len(svc.legacy_claims_of(kind="forecast")) == 1
    assert len(svc.legacy_claims_of(kind="fact")) == 1

    # ③ 显式兼容链的 locator 与 blocks 对齐 ⇒ claim 可溯源回原文。
    # 产品 fetch 在新链库只接受 cv2 句柄，不把此测试旧 doc_id 当回退入口。
    for row in by_ticker:
        blocks = svc.blocks_of(str(row["doc_id"]))
        assert any(str(block["locator"]) == str(row["locator"]) for block in blocks)


def test_extract_is_idempotent(fresh_svc) -> None:
    """重跑不得重复入库（UNIQUE + ON CONFLICT DO NOTHING）。"""
    svc = fresh_svc
    first = svc.extract_legacy_claims(llm=lambda prompt: FAKE_RESPONSE)
    assert first.claims >= 1, first.as_dict()
    before = len(svc.legacy_claims_of(limit=100))
    svc.extract_legacy_claims(llm=lambda prompt: FAKE_RESPONSE)
    after = len(svc.legacy_claims_of(limit=100))
    assert after == before, "重跑抽取产生了重复 claim"


def test_single_block_failure_does_not_stop_batch(fresh_svc) -> None:
    """LLM 单块失败只记 failure，不得中断整批（与 ingest 同一条纪律）。"""

    def flaky_llm(prompt: str) -> str:
        raise RuntimeError("LLM 超时")

    svc = fresh_svc
    stats = svc.extract_legacy_claims(llm=flaky_llm, retry_attempts=1)

    assert stats.failed >= 1, stats.as_dict()
    assert stats.failures, "失败必须带 locator 与原因，便于重试"
    assert "locator" in stats.failures[0]


# ── I2-7 写路径守卫：CORPUS_I2_DSN 未配置则拒绝一切 ingest（fail-closed） ──
def test_ingest_dir_requires_i2_sandbox_dsn(tmp_path, monkeypatch) -> None:
    """旧直写兜底已删除：ingest_dir 只能经 CORPUS_I2_DSN 走 preparation 引擎。"""
    monkeypatch.delenv("CORPUS_I2_DSN", raising=False)
    (tmp_path / "note.md").write_text("占位来源", encoding="utf-8")
    svc = CorpusService("postgresql://unused")
    with pytest.raises(RuntimeError, match="CORPUS_I2_DSN"):
        svc.ingest_dir(tmp_path)


def test_retry_recovers_from_transient_failure() -> None:
    """限流 / 抖动属瞬时失败：重试应能救回来（实测供应商会返回 429）。"""
    calls = {"n": 0}

    def flaky(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 限流")
        return FAKE_RESPONSE

    llm = with_retry(flaky, attempts=3, sleep=lambda _seconds: None)
    claims = extract_from_block(
        BlockView(1, "1", "营业收入 1741 亿元"), doc_id="2026-09-09_abcdef12", llm=llm
    )

    assert claims, "重试后应成功抽取"
    assert calls["n"] == 3


# ── 「钱不能白花」验收：逐块落库 / 跳过标记 / 指纹 / 熔断 / 死信 ──────
# LLM 调用是**不可逆的花费**，所以下面每条都在钉住一个会让钱白花的失败模式。
# 每个用例用**独立 schema**：互不共享状态，任意顺序都能跑。

COMMIT_DOC = "2026-09-09_d2commit"
COMMIT_BLOCKS = (
    (1, "1", "贵州茅台（600519.SH）2026H1 营业收入 1741 亿元，同比增长 1.3%"),
    (2, "2", "目标价 1888 元，维持增持评级"),
    (3, "3", "2026H1 毛利率 90.8%，同比提升 0.5 个百分点"),
)


def _claim_json(text: str, period: str = "2026H1") -> str:
    return json.dumps(
        [
            {
                "claim": text,
                "kind": "fact",
                "tickers": [],
                "metric": "营业收入",
                "value": "1741 亿元",
                "period": period,
                "confidence": 0.9,
            }
        ],
        ensure_ascii=False,
    )


E2E_DOC = "2026-09-09_d2e2e"
E2E_BLOCKS = (
    (
        1,
        "1",
        "贵州茅台（600519.SH）2026H1 营业收入约 1741 亿元，同比增长 1.3%。"
        "目标价 1888 元，维持增持评级。",
    ),
)


def _fresh_corpus_svc(doc_id: str, title: str, blocks: tuple):
    """独立 schema + 直插 documents/blocks 的 ``CorpusService``：用例间零共享状态。

    不走 ``ingest_dir``：I2-7 写路径已代理引擎链路（测试侧无 ``CORPUS_I2_DSN``），
    且切块规则会变，拿不稳「到底几个候选块」——直接写 ``documents`` /
    ``blocks``，保证恰好 ``len(blocks)`` 个候选块。
    """
    admin = dsn()
    try:
        psycopg.connect(admin, connect_timeout=5).close()
    except psycopg.OperationalError as exc:  # pragma: no cover - 环境相关
        pytest.skip(f"PG 不可用，跳过 D2 落库测试：{exc}")

    schema = f"corpus_d2c_{uuid.uuid4().hex[:8]}"
    url = _scratch_url(admin, schema)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    try:
        svc = CorpusService(url)
        svc.init_db()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO documents (doc_id, title, source_path, content_hash, mime,"
                    " status, char_count, block_count, published)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        doc_id,
                        title,
                        f"data/corpus/{doc_id}.md",
                        uuid.uuid4().hex,
                        "text/markdown",
                        "ok",
                        90,
                        len(blocks),
                        "2026-09-06",  # as_of 兜底的来源（§5.1）
                    ),
                )
                cur.executemany(
                    "INSERT INTO blocks (doc_id, seq, locator, text) VALUES (%s,%s,%s,%s)",
                    [(doc_id, seq, locator, text) for seq, locator, text in blocks],
                )
            conn.commit()
        yield svc
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.fixture
def fresh_svc():
    """三候选块文档：覆盖「钱不能白花」逐块落库/熔断语义。"""
    yield from _fresh_corpus_svc(COMMIT_DOC, "D2 落库验证", COMMIT_BLOCKS)


@pytest.fixture
def e2e_svc():
    """单候选块文档：端到端「一块抽出 2 条 claim」的原始查询语义。"""
    yield from _fresh_corpus_svc(E2E_DOC, "D2 端到端验证", E2E_BLOCKS)


def test_block_claims_survive_a_later_failure(fresh_svc) -> None:
    """★ 核心保证：第 1 块成功、第 2 块失败（429 / 超时）时，第 1 块必须已在库。

    旧实现把整份文档攒到末尾才提交，失败 / 中断会让**已花掉的钱全部蒸发**。
    """
    calls = {"n": 0}

    def llm(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return _claim_json("第一块已落库 1741 亿元")
        raise RuntimeError("429 Too Many Requests")

    stats = fresh_svc.extract_legacy_claims(
        llm=llm,
        retry_attempts=1,
        sleep_between=0,
        max_consecutive_failures=0,
    )

    assert stats.failed >= 1, stats.as_dict()
    texts = [str(row["claim_text"]) for row in fresh_svc.legacy_claims_of(limit=100)]
    assert any("第一块已落库" in text for text in texts), (
        "失败 / 中断后已完成块的 claim 丢了 —— 这正是要修的失败模式"
    )
    failing = fresh_svc.block_runs(status="failed")
    assert failing and "429" in str(failing[0]["error"]), "失败必须留痕（含原因）"


def test_stop_request_keeps_committed_blocks(fresh_svc) -> None:
    """中断（Ctrl-C）：当前块之后干净退出，已提交的块必须还在库里。"""
    seen = {"n": 0}

    def llm(prompt: str) -> str:
        seen["n"] += 1
        return _claim_json(f"第 {seen['n']} 块已落库")

    stats = fresh_svc.extract_legacy_claims(
        llm=llm,
        retry_attempts=1,
        sleep_between=0,
        should_stop=lambda: seen["n"] >= 1,  # 做完第 1 块就等于"收到信号"
    )

    assert stats.stopped_early is True
    assert stats.stopped_reason, "提前退出必须说明原因"
    assert seen["n"] == 1, "中断后不该再调模型"
    rows = fresh_svc.legacy_claims_of(limit=100)
    assert len(rows) == 1 and "第 1 块已落库" in str(rows[0]["claim_text"])


def test_rerun_skips_blocks_that_yielded_zero_claims(fresh_svc) -> None:
    """「抽出 0 条 claim」的块也算做过 —— 否则每次重跑都要为它再烧一次钱。"""
    calls = {"n": 0}

    def empty_llm(prompt: str) -> str:
        calls["n"] += 1
        return "[]"

    first = fresh_svc.extract_legacy_claims(llm=empty_llm, retry_attempts=1, sleep_between=0)
    assert first.candidates == len(COMMIT_BLOCKS) and first.claims == 0
    assert calls["n"] == len(COMMIT_BLOCKS)

    calls["n"] = 0
    second = fresh_svc.extract_legacy_claims(llm=empty_llm, retry_attempts=1, sleep_between=0)

    assert calls["n"] == 0, "抽出 0 条的块被重复调用了 LLM（重复花钱）"
    assert second.skipped_existing == len(COMMIT_BLOCKS)
    marks = fresh_svc.block_runs()
    assert {str(m["status"]) for m in marks} == {"ok"}
    assert {int(m["claims_n"]) for m in marks} == {0}


def test_failed_blocks_are_retried_on_rerun(fresh_svc) -> None:
    """失败块不算「已完成」：重跑必须重试，否则数据永远抽不出来。"""
    calls = {"n": 0}

    def flaky(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] <= len(COMMIT_BLOCKS):
            raise RuntimeError("429 Too Many Requests")
        return _claim_json("第二轮补上了 1741 亿元")

    first = fresh_svc.extract_legacy_claims(
        llm=flaky,
        retry_attempts=1,
        sleep_between=0,
        max_consecutive_failures=0,
    )
    assert first.failed == len(COMMIT_BLOCKS)

    second = fresh_svc.extract_legacy_claims(
        llm=flaky,
        retry_attempts=1,
        sleep_between=0,
        max_consecutive_failures=0,
    )
    assert second.skipped_existing == 0, "失败块被当成了已完成，重跑直接跳过"
    assert second.claims == len(COMMIT_BLOCKS), "失败块没有被重试"


def test_fingerprint_change_reextracts_and_replaces(fresh_svc, monkeypatch) -> None:
    """换模型 / 改 prompt（指纹变化）必须自动重抽，并整块替换旧结果。

    否则两个事故同时发生：① 旧块被**静默永久跳过**（换模型等于没换，还不报错）；
    ② 表里混着两代模型的结果（``ON CONFLICT`` 只挡完全相同的文本）。

    各块 period 互异（按调用顺序编号）：块间坐标不同才不会被 P3 跨块去重合并，
    这个测才能钉住「3 块各有 1 条、换指纹后 3 条整批替换」本身。
    """
    seqs = {"n": 0}

    def llm_factory(tag: str) -> Callable[[str], str]:
        def llm(prompt: str) -> str:
            seqs["n"] += 1
            return _claim_json(f"{tag} 口径 1741 亿元", period=f"2026H{seqs['n']}")

        return llm

    seqs["n"] = 0
    old_claims = fresh_svc.extract_legacy_claims(
        llm=llm_factory("GLM-4.7"),
        retry_attempts=1,
        sleep_between=0,
    )
    assert old_claims.claims == len(COMMIT_BLOCKS)

    monkeypatch.setattr("plugins.corpus.service.EXTRACTOR_VERSION", "v2-test")
    seqs["n"] = 0
    new_claims = fresh_svc.extract_legacy_claims(
        llm=llm_factory("AirX"),
        retry_attempts=1,
        sleep_between=0,
    )

    assert new_claims.claims == len(COMMIT_BLOCKS), "指纹变了却没重抽 —— 换模型会静默失效"
    texts = [str(row["claim_text"]) for row in fresh_svc.legacy_claims_of(limit=100)]
    assert sum("AirX 口径" in text for text in texts) == len(COMMIT_BLOCKS)
    assert not any("GLM-4.7 口径" in text for text in texts), "两代模型的结果混在一张表里"


def test_circuit_breaker_stops_after_consecutive_failures(fresh_svc) -> None:
    """额度耗尽 / 429 风控时必须熔断退出，不能继续把剩下的额度烧在重试上。"""
    calls = {"n": 0}

    def always_429(prompt: str) -> str:
        calls["n"] += 1
        raise RuntimeError("429 Too Many Requests")

    stats = fresh_svc.extract_legacy_claims(
        llm=always_429,
        retry_attempts=1,
        sleep_between=0,
        max_consecutive_failures=2,
    )

    assert stats.stopped_early is True
    assert "连续 2 块失败" in (stats.stopped_reason or "")
    assert calls["n"] == 2, f"已熔断却还在调模型：{calls['n']} 次"
    assert stats.candidates == 2


def test_dead_letter_is_not_retried_forever(fresh_svc) -> None:
    """反复失败的块达到次数上限后不再重试 —— 否则每次重跑都白花一笔。"""
    calls = {"n": 0}

    def always_429(prompt: str) -> str:
        calls["n"] += 1
        raise RuntimeError("429 Too Many Requests")

    def run():
        return fresh_svc.extract_legacy_claims(
            llm=always_429,
            retry_attempts=1,
            sleep_between=0,
            max_consecutive_failures=0,
            max_attempts=3,
        )

    for _ in range(3):  # 三轮之后每块 attempts 达到上限 3
        assert run().failed == len(COMMIT_BLOCKS)

    calls["n"] = 0
    last = run()
    assert last.skipped_dead_letter == len(COMMIT_BLOCKS), last.as_dict()
    assert calls["n"] == 0, "死信块又被重试了 —— 会一直白花钱"


# ── 文档级标的兜底 ───────────────────────────────────────────────
# 表格块里没有代码列，模型抽不出 ticker；而 D3/D4 是按 ticker 聚合的。
# 实测一份贵州茅台研报 121 条 claim 的 tickers 全空 ⇒ 这些数据等于白抽。
def test_document_ticker_reads_strict_form() -> None:
    assert document_ticker("贵州茅台（600519.SH）2026 中报点评", []) == "600519.SH"
    assert document_ticker("某公司研究", ["……（002694.SZ）……"]) == "002694.SZ"
    # 正文里中文紧跟代码也必须能认出（\w 是 Unicode 语义，中文会被误判成词字符）
    assert document_ticker("某公司研究", ["600519.SH股票"]) == "600519.SH"


def test_document_ticker_maps_bare_code_in_title() -> None:
    """券商研报文件名常把代码写成裸 6 位（没有 .SH / .SZ 后缀）。"""
    assert (
        document_ticker("2026.08.17-国信证券-业绩点评-贵州茅台-600519-2026中报.pdf", [])
        == "600519.SH"
    )
    assert document_ticker("国信证券-光力科技-300480-2026年中报.pdf", []) == "300480.SZ"


def test_document_ticker_ignores_bare_code_in_body() -> None:
    """正文里的裸 6 位不采信：业绩年份（202609）、页码、金额都会误命中。

    兜底值会写进该文档**所有** claim，猜错的代价是整份文档标的全错。
    """
    assert document_ticker("某公司研究", ["202609 营业收入 123456 万元"]) is None


def test_document_ticker_abstains_on_industry_reports() -> None:
    """行业 / 策略报告正文里有一堆公司代码 —— 不能给整份文档硬塞一个标的。

    实测：同一份化工专题正文出现 **53 个**代码、机器人行业周报 **46 个**。
    错误的坐标比缺失的坐标更危险（下游无法察觉），所以多码时一律放弃。
    """
    industry = "可比公司：002694.SZ 雅克科技、002409.SZ 英力特、603299.SH 苏盐井神"
    assert document_ticker("长江证券-化工专题-景气投资十问十答", [industry]) is None
    # 正文里**唯一**一个代码 ⇒ 全文就在讲这一家，可以采信
    assert document_ticker("某公司研究", ["……（600519.SH）……"]) == "600519.SH"


def test_document_ticker_skips_invalid_bare_candidates() -> None:
    """标题里先出现的 6 位数字若号段不合法（如业绩年份 202609），必须继续往后找。"""
    assert document_ticker("202609-贵州茅台-600519-中报点评.pdf", []) == "600519.SH"


def test_document_ticker_returns_none_when_unknown() -> None:
    assert document_ticker("行业周报", ["没有任何代码"]) is None
    assert document_ticker(None, []) is None


def test_apply_doc_ticker_respects_model_value() -> None:
    """模型给了 ticker 就尊重模型（它看得到块内代码列），只在为空时兜底。"""
    claims = [
        Claim(doc_id="d", seq=1, locator="1", claim_text="甲 1741 亿元", tickers=("000001.SZ",)),
        Claim(doc_id="d", seq=1, locator="1", claim_text="乙 1741 亿元"),
    ]
    filled = apply_doc_ticker(claims, "600519.SH")
    assert filled[0].tickers == ("000001.SZ",)
    assert filled[1].tickers == ("600519.SH",)
    assert apply_doc_ticker(claims, None)[1].tickers == ()


def test_document_ticker_fallback_fills_table_blocks(fresh_svc) -> None:
    """端到端：模型没给 ticker 时，落库的 claim 必须带上文档级标的。"""
    stats = fresh_svc.extract_legacy_claims(
        llm=lambda prompt: _claim_json("营业收入 1741 亿元"),
        retry_attempts=1,
        sleep_between=0,
    )
    assert stats.claims == len(COMMIT_BLOCKS)

    rows = fresh_svc.legacy_claims_of(limit=100)
    assert rows and all(list(row["tickers"]) == ["600519.SH"] for row in rows), (
        "文档级标的兜底没生效 —— 这些 claim 在按 ticker 聚合时会全部落空"
    )


# ── P1：文档领域分类（§3.1） ─────────────────────────────────────
def test_classify_doc_kind_company() -> None:
    """标题含代码（严格/裸号段）或正文唯一代码 ⇒ company。"""
    assert classify_doc_kind("贵州茅台（600519.SH）2026 中报点评", []) == "company"
    assert classify_doc_kind("2026.08.17-国信证券-贵州茅台-600519-中报点评", []) == "company"
    assert classify_doc_kind("某公司研究", ["……（600519.SH）……"]) == "company"


def test_classify_doc_kind_industry() -> None:
    """正文多个代码 ⇒ industry（行业报告列举一堆公司），即使标题带宏观词。"""
    multi = ["002694.SZ 雅克科技", "002409.SZ 英力特", "603299.SH 苏盐井神"]
    assert classify_doc_kind("化工专题", multi) == "industry"
    assert classify_doc_kind("策略周报", multi) == "industry"


def test_classify_doc_kind_macro() -> None:
    """无代码 + 宏观/策略词 ⇒ macro；无代码无任何词 ⇒ industry（宁缺勿错）。"""
    assert classify_doc_kind("华创证券-宏观专题-从分化到收敛", []) == "macro"
    assert classify_doc_kind("美联储加息预期升温", []) == "macro"
    assert classify_doc_kind("美国非农数据点评", []) == "industry", (
        "标题只有指标词（非农）不在保守词表内 —— 正是缺口#1 要用 override 纠正的场景"
    )
    assert classify_doc_kind("行业数据周报", ["锂电排产环比上升 3%"]) == "industry"


# ── P1：插槽选择（§3.2） ────────────────────────────────────────
def test_build_prompt_selects_slot_by_doc_kind() -> None:
    text = "新增非农就业 16.2 万人"
    macro_prompt = build_prompt(text, doc_kind="macro")
    assert "US.NFP" in macro_prompt, "macro 插槽必须带编码规范与双语词表"
    assert "consensus" in macro_prompt, "三态拆分是 macro 插槽的核心（缺陷 1）"
    company_prompt = build_prompt(text, doc_kind="company")
    assert "营业收入" in company_prompt
    industry_prompt = build_prompt(text, doc_kind="industry")
    assert "<主体>.<指标>" in industry_prompt, "industry 插槽必须带两段式编码规范（§5.3）"
    assert "基础化工" in industry_prompt, "industry 插槽必须带主体词表示例"
    assert "三态拆分" in industry_prompt and "不需要" in industry_prompt, (
        "industry 不做三态拆分（§3.2 插槽表）—— 防止把 macro 契约错套到行业报告"
    )
    with pytest.raises(ValueError, match="doc_kind"):
        build_prompt(text, doc_kind="板块")  # 未知领域必须炸出来，不能静默用错插槽


def test_extract_from_block_passes_doc_kind_to_prompt() -> None:
    seen: list[str] = []

    def llm(prompt: str) -> str:
        seen.append(prompt)
        return "[]"

    extract_from_block(BlockView(1, "1", "失业率 4.1%"), doc_id="d", llm=llm, doc_kind="macro")
    assert seen and "US.NFP" in seen[0]


# ── P2：industry 插槽 + 坐标模型强制（§3.3） ─────────────────────
def test_extract_from_block_enforces_coordinate_model() -> None:
    """模型越界给了 tickers 也必须在解析层清空 —— 行业报告正文 53 个代码的诱惑太大。

    company 不受影响：模型给的 tickers 是坐标本体（§3.3 company→tickers）。
    """

    def llm(prompt: str) -> str:
        return json.dumps(
            [
                {
                    "claim": "基础化工.最高涨幅 291.4%",
                    "kind": "fact",
                    "tickers": ["002694.SZ"],  # 越界：行业报告里模型抄了正文代码
                    "metric": "基础化工.最高涨幅",
                    "value": "291.4%",
                    "period": "2016-2018",
                    "confidence": 0.9,
                }
            ],
            ensure_ascii=False,
        )

    block = BlockView(1, "1", "基础化工行业 2016-2018 年最高涨幅 291.4%")
    industry_claims = extract_from_block(block, doc_id="d", llm=llm, doc_kind="industry")
    assert industry_claims and all(c.tickers == () for c in industry_claims), (
        "industry 文档的 claim 不得携带 tickers（§3.3）"
    )
    company_claims = extract_from_block(block, doc_id="d", llm=llm, doc_kind="company")
    assert company_claims and all(c.tickers == ("002694.SZ",) for c in company_claims), (
        "company 文档的模型 tickers 必须原样保留"
    )


def test_industry_doc_end_to_end_slot_and_tickers(fresh_svc) -> None:
    """industry 端到端：插槽选择、解析层强制清空 tickers、服务层不给文档级标的。

    fixture 文档正文只有一个严格代码（600519.SH）会被自动判成 company —— 这里用
    ``set_doc_kind`` 覆盖成 industry（缺口#1 纠正入口的 industry 用法；自动分类的
    多代码规则已由 ``test_classify_doc_kind_industry`` 覆盖）。
    """
    prompts: list[str] = []

    def llm(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            [
                {
                    "claim": "钛白粉价格 15800 元/吨",
                    "kind": "fact",
                    "tickers": ["002694.SZ"],  # 故意越界，验证解析层强制清空
                    "metric": "钛白粉.价格",
                    "value": "15800 元/吨",
                    "period": None,
                    "as_of": None,
                    "confidence": 0.9,
                }
            ],
            ensure_ascii=False,
        )

    fresh_svc.set_doc_kind(COMMIT_DOC, "industry")
    stats = fresh_svc.extract_legacy_claims(llm=llm, retry_attempts=1, sleep_between=0)
    assert stats.claims == len(COMMIT_BLOCKS), stats.as_dict()
    assert all("<主体>.<指标>" in p for p in prompts), "industry 文档没用 industry 插槽"

    rows = fresh_svc.legacy_claims_of(limit=100)
    assert rows and all(list(row["tickers"]) == [] for row in rows), (
        "industry 文档的 tickers 必须全空 —— 服务层不给文档级标的，解析层清掉模型越界值"
    )
    assert all(str(row["metric"]) == "钛白粉.价格" for row in rows)


# ── P1：事实列解析（§5.1） ──────────────────────────────────────
def test_parse_value_splits_number_and_unit() -> None:
    assert parse_value("173,340 百万元") == (Decimal("173340"), "百万元")
    assert parse_value("4.1%") == (Decimal("4.1"), "%")
    assert parse_value("65.77 元") == (Decimal("65.77"), "元")
    assert parse_value("-2.3 万人") == (Decimal("-2.3"), "万人")
    assert parse_value("+1bp") == (Decimal("1"), "bp")
    assert parse_value("16.2万人") == (Decimal("16.2"), "万人")


def test_parse_value_handles_accounting_parens() -> None:
    """研报财务表用括号表负数：``(325)`` = -325。"""
    assert parse_value("(325)") == (Decimal("-325"), None)
    assert parse_value("(325) 百万元") == (Decimal("-325"), "百万元")


def test_parse_value_never_guesses() -> None:
    """解析失败必须返回 (None, None)，保留 value_text 原文，不得猜。"""
    assert parse_value(None) == (None, None)
    assert parse_value("") == (None, None)
    assert parse_value("增持") == (None, None)
    assert parse_value("约翻倍") == (None, None)


def test_parse_as_of_accepts_iso_and_chinese_dates() -> None:
    assert parse_as_of("2026-09-04") == "2026-09-04"
    assert parse_as_of("2026年9月4日") == "2026-09-04"
    assert parse_as_of("2026/9/4") == "2026-09-04"


def test_parse_as_of_rejects_non_dates() -> None:
    """不是明确的日期就返回 None（published 兜底），不猜。"""
    assert parse_as_of(None) is None
    assert parse_as_of("2026-02-30") is None
    assert parse_as_of("2026 年 9 月") is None
    assert parse_as_of("上周五") is None


def test_claims_from_payload_derives_fact_columns() -> None:
    claims = claims_from_payload(
        [
            {
                "claim": "新增非农就业 16.2 万人",
                "kind": "fact",
                "metric": "US.NFP.actual",
                "value": "16.2 万人",
                "period": "2026-08",
                "as_of": "2026年9月4日",
            },
            {
                "claim": "预期 5.6 万人",
                "kind": "forecast",
                "metric": "US.NFP.consensus",
                "value": "(5.6) 万人",  # 模型偶尔把负数写成括号
                "as_of": "上周五",  # 非法日期 ⇒ None，交由 published 兜底
            },
        ],
        doc_id="d",
        seq=3,
        locator="3",
    )
    assert claims[0].value_num == Decimal("16.2") and claims[0].unit == "万人"
    assert claims[0].as_of == "2026-09-04"
    assert claims[1].value_num == Decimal("-5.6") and claims[1].unit == "万人"
    assert claims[1].as_of is None


def test_apply_as_of_fallback_fills_from_published() -> None:
    claims = [
        Claim(doc_id="d", seq=1, locator="1", claim_text="甲 16.2 万人", as_of="2026-09-04"),
        Claim(doc_id="d", seq=1, locator="1", claim_text="乙 5.6 万人"),
    ]
    filled = apply_as_of_fallback(claims, "2026-09-06")
    assert filled[0].as_of == "2026-09-04", "模型给了就尊重模型"
    assert filled[1].as_of == "2026-09-06", "缺失时必须用 documents.published 兜底"
    assert apply_as_of_fallback(claims, None)[1].as_of is None
    assert apply_as_of_fallback(claims, "无法解析")[1].as_of is None


# ── P1：三列落库 + macro 端到端 ─────────────────────────────────
def test_macro_doc_uses_macro_slot_and_fact_columns(fresh_svc) -> None:
    """macro 文档端到端：插槽选择、三列落库、ticker 门控、as_of 兜底。

    fixture 文档正文含唯一代码（600519.SH）会被自动判成 company —— 这里用
    ``set_doc_kind`` 覆盖成 macro，同时验证缺口#1 的纠正入口确实生效。
    """
    prompts: list[str] = []

    def llm(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            [
                {
                    "claim": "新增非农就业 16.2 万人",
                    "kind": "fact",
                    "tickers": [],
                    "metric": "US.NFP.actual",
                    "value": "16.2 万人",
                    "period": "2026-08",
                    "as_of": None,
                    "confidence": 0.9,
                }
            ],
            ensure_ascii=False,
        )

    fresh_svc.set_doc_kind(COMMIT_DOC, "macro")
    stats = fresh_svc.extract_legacy_claims(llm=llm, retry_attempts=1, sleep_between=0)
    assert stats.claims == len(COMMIT_BLOCKS), stats.as_dict()
    assert any("US.NFP" in p for p in prompts), "macro 文档没用 macro 插槽"

    rows = fresh_svc.legacy_claims_of(limit=100)
    assert rows and all(list(row["tickers"]) == [] for row in rows), (
        "macro 文档不得给文档级标的兜底（§3.1 副产品），即使正文里有代码"
    )
    assert all(str(row["value_num"]) == "16.2" and row["unit"] == "万人" for row in rows)
    assert all(str(row["as_of"]) == "2026-09-06" for row in rows), (
        "模型没给 as_of 时必须用 published 兜底（§5.1）"
    )


# ── P7：company 插槽端到端（现有模板原样收编的验收钉） ──────────
def test_company_doc_uses_company_slot_and_keeps_tickers(fresh_svc) -> None:
    """company 端到端：插槽选择、模型 tickers 原样保留、metric 不加前缀。

    fixture 文档正文含唯一代码（600519.SH）本就会自动判成 company —— 这里显式
    ``set_doc_kind`` 覆盖成 company，与 industry / macro 的端到端用例对称，
    钉死缺口#1 纠正入口的第三种用法（§9 P7：现有模板原样收编）。
    """
    prompts: list[str] = []

    def llm(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            [
                {
                    "claim": "贵州茅台 2026H1 营业收入 1741 亿元",
                    "kind": "fact",
                    "tickers": ["600519.SH"],
                    "metric": "营业收入",
                    "value": "1741 亿元",
                    "period": "2026H1",
                    "as_of": None,
                    "confidence": 0.9,
                }
            ],
            ensure_ascii=False,
        )

    fresh_svc.set_doc_kind(COMMIT_DOC, "company")
    stats = fresh_svc.extract_legacy_claims(llm=llm, retry_attempts=1, sleep_between=0)
    assert stats.claims == len(COMMIT_BLOCKS), stats.as_dict()
    assert all("公司研报" in p for p in prompts), "company 文档没用 company 插槽"
    assert all("<主体>.<指标>" not in p for p in prompts), (
        "company 插槽不得混入 industry 的编码规则"
    )

    rows = fresh_svc.legacy_claims_of(limit=100)
    assert rows and all(list(row["tickers"]) == ["600519.SH"] for row in rows), (
        "company 文档的模型 tickers 是坐标本体，必须原样保留（§3.3）"
    )
    assert all(str(row["metric"]) == "营业收入" for row in rows), (
        "company 的 metric 用裸中文指标名，不加任何前缀"
    )


def test_set_doc_kind_validates_and_clears(fresh_svc) -> None:
    with pytest.raises(ValueError, match="doc_kind"):
        fresh_svc.set_doc_kind(COMMIT_DOC, "板块")
    fresh_svc.set_doc_kind(COMMIT_DOC, "macro")
    row = {str(d["doc_id"]): d for d in fresh_svc._legacy_documents()}[COMMIT_DOC]
    assert str(row["doc_kind_override"]) == "macro"
    fresh_svc.set_doc_kind(COMMIT_DOC, None)
    row = {str(d["doc_id"]): d for d in fresh_svc._legacy_documents()}[COMMIT_DOC]
    assert row["doc_kind_override"] is None, "None 必须清除覆盖、恢复自动分类"


def test_backup_columns_track_claims_schema() -> None:
    """§5.1 纪律：新增列必须同步 _BACKUP_COLUMNS，漏列会静默丢字段（踩过）。"""
    cols = set(CorpusService._BACKUP_COLUMNS["claims"])
    assert {"value_num", "unit", "as_of"} <= cols
    assert "entities" not in cols, "entities 死字段已按缺口#4 删除"


def test_doc_kind_constants_are_closed_world() -> None:
    assert DOC_KINDS == ("company", "industry", "macro")


# ── P3：别名归并 + 单位基准 + 跨块去重（§3.4 / §5.1） ────────────
def test_normalize_metric_merges_known_aliases() -> None:
    """缺陷 3：EPS 与 每股收益 并存会让聚合只命中一半。"""
    assert normalize_metric("EPS") == "每股收益"
    assert normalize_metric("eps") == "每股收益", "大小写不敏感（仅查表用）"
    assert normalize_metric("每股盈利") == "每股收益"
    assert normalize_metric(" 每股收益 ") == "每股收益", "空白折叠"


def test_normalize_metric_never_touches_coordinates() -> None:
    """industry / macro 的分段坐标编码不能被别名表碰坏；未命中原样返回。"""
    assert normalize_metric("US.NFP.actual") == "US.NFP.actual", "大小写必须保留"
    assert normalize_metric("基础化工.价格") == "基础化工.价格"
    assert normalize_metric("营业收入") == "营业收入"
    assert normalize_metric(None) is None
    assert normalize_metric("") == ""


def test_claims_from_payload_applies_metric_alias() -> None:
    claims = claims_from_payload(
        [
            {
                "claim": "2026E 每股收益 65.77 元",
                "kind": "forecast",
                "metric": "EPS",
                "value": "65.77 元",
                "period": "2026E",
            }
        ],
        doc_id="d",
        seq=1,
        locator="1",
    )
    assert claims[0].metric == "每股收益"
    assert claims[0].value_num == Decimal("65.77"), "归并不影响事实列派生"


def test_unit_scale_maps_money_units_to_base() -> None:
    """§5.1：万元/百万元/亿元 → 基准单位（元）+ 倍数；value_num 本身不改写。"""
    assert unit_scale("亿元") == (Decimal("1e8"), "元")
    assert unit_scale("百万元") == (Decimal("1e6"), "元")
    assert unit_scale("万元") == (Decimal("1e4"), "元")
    assert unit_scale("元") == (Decimal(1), "元")
    assert unit_scale(" 亿元 ") == (Decimal("1e8"), "元"), "模型给的单位可能带空白"
    assert unit_scale("%") == (Decimal(1), "%"), "未知单位原样，倍数 1"
    assert unit_scale("万人") == (Decimal(1), "万人")
    assert unit_scale(None) == (Decimal(1), "")
    assert unit_scale("") == (Decimal(1), "")


def test_dedup_claims_preserves_unresolved_coordinate_conflicts() -> None:
    """Different observations cannot be silently interpreted as later corrections."""

    def claim(seq: int, metric: str | None, period: str | None, kind: str, text: str) -> Claim:
        return Claim(
            doc_id="d",
            seq=seq,
            locator=str(seq),
            claim_text=text,
            kind=kind,
            metric=metric,
            period=period,
        )

    claims = [
        claim(1, "毛利率", "2026E", "fact", "毛利率 90.4%"),
        claim(1, "毛利率", "2026E", "fact", "毛利率 90.42%"),  # 同坐标，保留这条
        claim(1, "毛利率", "2026E", "forecast", "预计毛利率 91%"),  # kind 不同 → 保留
        claim(1, "毛利率", "2027E", "fact", "毛利率 91.2%"),  # period 不同 → 保留
        claim(1, None, None, "fact", "无指标坐标"),  # metric 空 → 不参与
        claim(1, None, None, "fact", "无指标坐标也保留"),
    ]
    kept = _dedup_claims(claims)
    assert len(kept) == 6
    assert [
        c.claim_text
        for c in kept
        if c.metric == "毛利率" and c.kind == "fact" and c.period == "2026E"
    ] == ["毛利率 90.4%", "毛利率 90.42%"]
    assert [c.claim_text for c in kept if c.metric is None] == [
        "无指标坐标",
        "无指标坐标也保留",
    ]
    assert _dedup_claims([]) == []


def test_cross_block_dedup_preserves_conflicting_values(fresh_svc) -> None:
    """★ 缺陷 4 端到端：毛利率 2026E 跨块重复 2 条 → 1 条，幸存行 value_num 可取。

    seq=1 与 seq=2 给同坐标不同精度的表述（90.4% / 90.42%，文本不同，
    UNIQUE 挡不住），seq=3 给同 metric 但 kind=forecast —— 必须分开保留。
    """
    responses = [
        json.dumps(
            [
                {
                    "claim": "毛利率 90.4%",
                    "kind": "fact",
                    "tickers": [],
                    "metric": "毛利率",
                    "value": "90.4%",
                    "period": "2026E",
                },
                {
                    "claim": "维持买入评级",
                    "kind": "forecast",
                    "tickers": [],
                    "metric": None,
                    "value": None,
                    "period": None,
                },
            ],
            ensure_ascii=False,
        ),
        json.dumps(
            [
                {
                    "claim": "毛利率 90.42%（表格口径）",
                    "kind": "fact",
                    "tickers": [],
                    "metric": "毛利率",
                    "value": "90.42%",
                    "period": "2026E",
                }
            ],
            ensure_ascii=False,
        ),
        json.dumps(
            [
                {
                    "claim": "预计 2026E 毛利率 91%",
                    "kind": "forecast",
                    "tickers": [],
                    "metric": "毛利率",
                    "value": "91%",
                    "period": "2026E",
                }
            ],
            ensure_ascii=False,
        ),
    ]

    def llm(prompt: str) -> str:
        return responses.pop(0)

    stats = fresh_svc.extract_legacy_claims(llm=llm, retry_attempts=1, sleep_between=0)
    # stats.claims 累计每次提交的净插入数（2+1+1=4，跨块删除不计入）；
    # 库里净存 3 条 —— seq=1 的毛利率行被 seq=2 同坐标覆盖。
    assert stats.claims == 4, stats.as_dict()

    rows = fresh_svc.legacy_claims_of(limit=100)
    assert len(rows) == 4, f"Conflicting observations must survive: {rows}"
    gross_rate_fact = [r for r in rows if r["metric"] == "毛利率" and r["kind"] == "fact"]
    assert len(gross_rate_fact) == 2
    assert {r["value_num"] for r in gross_rate_fact} == {Decimal("90.4"), Decimal("90.42")}
    assert {int(r["seq"]) for r in gross_rate_fact} == {1, 2}

    forecast = [r for r in rows if r["metric"] == "毛利率" and r["kind"] == "forecast"]
    assert len(forecast) == 1, "kind 不同不算重复，不得误删"
    no_metric = [r for r in rows if r["metric"] is None]
    assert len(no_metric) == 1, "metric 为空的行不参与去重"


# ── P4：表格块判据 + 追加段 + 输出上限（§3.2 第 4 轴 / §10 Q5 / 缺口#3） ──

#: 真·被压平表格的形态（取自 2026-08-17_c195233b seq=4 财务预测与估值三表：
#: ingest 把表格压平成单元格流，行名与数值逐行排开、行列关系丢失）
_FLAT_TABLE_SAMPLE = "\n".join(
    [
        "证券研究报告",
        "财务预测与估值",
        "资产负债表（百万元）",
        "2026E",
        "2027E",
        "2028E",
        "利润表（百万元）",
        "2026E",
        "2027E",
        "2028E",
        "现金及现金等价物",
        "营业收入",
        "应收款项",
        "营业成本",
        "存货净额",
        "营业税金及附加",
        "其他流动资产",
        "销售费用",
        "(1470)",
        "(815)",
        "(2213)",
        "归属于母公司净利润",
        "每股收益",
        "68.64",
        "65.74",
        "65.77",
        "70.77",
        "77.66",
        "ROIC",
        "77.5%",
        "70.9%",
        "61.1%",
        "59.4%",
        "62.2%",
        "毛利率",
        "92.1%",
        "91.3%",
        "90.4%",
        "资料来源：Wind、国信证券经济研究所预测",
    ]
)


def test_is_flat_table_detects_flattened_financial_table() -> None:
    assert is_flat_table(_FLAT_TABLE_SAMPLE), "财务三表单元格流必须被判为表格（缺陷 6）"


def test_is_flat_table_rejects_prose_even_when_number_dense() -> None:
    prose = "\n".join(
        [
            "公司 2026 年上半年实现营业收入 1741.44 亿元，同比增长 1.3%；归母净利润 862.26 亿元。",
            "2026 年下半年，公司将持续深化市场化改革，产品结构进一步优化，直营渠道占比稳步提升。",
            "展望全年，我们预计营业收入同比增长 15.7%，归母净利润同比增长 15.4%，维持买入评级。",
            "风险提示：宏观经济下行、行业竞争加剧、食品安全事件等可能对公司业绩产生影响。",
            "目标价 1888 元，对应 2026 年 22 倍 PE，估值中枢仍有抬升空间，维持增持评级不变。",
        ]
    )
    assert is_flat_table(prose) is False, "数字密集的散文被判成表格会让插槽契约跑偏"


def test_is_flat_table_rejects_toc_dot_leaders_and_short_fragments() -> None:
    tocish = "\n".join(f"8-17 {'.' * 8} 4" for _ in range(10))
    assert is_flat_table(tocish) is False, "点线引导符（目录页）必须被排除"
    assert is_flat_table("18.4%\n43.7%\n0.76%") is False, "短片段凑不成表格"


def test_build_prompt_appends_table_section_for_flat_tables_only() -> None:
    table_prompt = build_prompt(_FLAT_TABLE_SAMPLE, doc_kind="company")
    assert "被压平的表格" in table_prompt, "表格块必须追加逐格抽取规则（§3.2 第 4 轴）"
    assert "子表前缀" in table_prompt and "利润表" in TABLE_APPENDIX
    assert table_prompt.find("按表格出现顺序") < table_prompt.find("原文："), "追加段在原文之前"

    prose_prompt = build_prompt(
        "公司 2026 年上半年实现营业收入 1741.44 亿元，同比增长 1.3%。", doc_kind="company"
    )
    assert "被压平的表格" not in prose_prompt, "散文块不得追加表格规则"


def test_extractor_version_input_includes_table_appendix() -> None:
    assert TABLE_APPENDIX in claims_mod._PROMPT_PARTS, "表格追加段必须纳入指纹（§3.2 指纹对接）"
    assert claims_mod._EXTRACTOR_REV == 5, "解析口径变化（截断抢救）必须推进人工版本号"


def test_extract_from_block_sends_table_appendix_for_table_blocks() -> None:
    seen: list[str] = []

    def llm(prompt: str) -> str:
        seen.append(prompt)
        return "[]"

    extract_from_block(
        BlockView(4, "4", _FLAT_TABLE_SAMPLE), doc_id="d", llm=llm, doc_kind="company"
    )
    assert seen and "被压平的表格" in seen[0]


def test_extract_from_block_drops_unanchored_periods_in_table_blocks() -> None:
    """表格块 period 锚定护栏：压平丢列头时模型会编 2029E 凑数（P4 实测 18 条），
    解析层强制 period 必须逐字出现在块文本里，锚不到的整条丢弃（宁缺勿错）。
    散文块不适用 —— 模型把「2026 年上半年」规范化成 2026H1 是合法的。
    """
    raw = json.dumps(
        [
            {
                "claim": "利润表.每股收益 2026E 65.77 元",
                "kind": "fact",
                "tickers": [],
                "metric": "利润表.每股收益",
                "value": "65.77 元",
                "period": "2026E",
            },
            {
                "claim": "利润表.每股收益 2030E 77.66 元",
                "kind": "fact",
                "tickers": [],
                "metric": "利润表.每股收益",
                "value": "77.66 元",
                "period": "2030E",
            },
            {
                "claim": "利润表.财务费用 (815)",
                "kind": "fact",
                "tickers": [],
                "metric": "利润表.财务费用",
                "value": "(815)",
                "period": None,
            },
        ],
        ensure_ascii=False,
    )

    claims = extract_from_block(
        BlockView(4, "4", _FLAT_TABLE_SAMPLE),
        doc_id="d",
        llm=lambda prompt: raw,
        doc_kind="company",
    )
    kept = {(c.metric, c.period) for c in claims}
    assert kept == {
        ("利润表.每股收益", "2026E"),
        ("利润表.财务费用", None),
    }, "2026E 在块文本里保留；编造的 2030E 整条丢弃；period=None 不受约束"

    prose_claims = extract_from_block(
        BlockView(1, "1", "2026 年上半年实现营业收入 1741 亿元"),
        doc_id="d",
        llm=lambda prompt: json.dumps(
            [
                {
                    "claim": "营业收入 1741 亿元",
                    "kind": "fact",
                    "tickers": [],
                    "metric": "营业收入",
                    "value": "1741 亿元",
                    "period": "2026H1",
                }
            ]
        ),
        doc_kind="company",
    )
    assert prose_claims[0].period == "2026H1", "散文块允许规范化期间（护栏只管表格块）"


def test_parse_claims_json_salvages_truncated_array() -> None:
    """max_tokens 截断是设计内行为（§10 Q5）：已完整的对象前缀必须抢救回来。"""
    out = parse_claims_json(
        '[{"claim": "毛利率 90.4%", "metric": "毛利率", "value": "90.4%"}, {"claim": "EPS'
    )
    assert len(out) == 1 and out[0]["metric"] == "毛利率"

    out2 = parse_claims_json('[{"claim": "a", "metric": "m"},{')
    assert len(out2) == 1, "截断点恰在完整对象之后（下一个对象已开括号）也应抢救"

    assert len(parse_claims_json('[{"claim": "a"}, {"claim": "b"}]')) == 2, "完整数组不受影响"
    assert parse_claims_json('[{"claim": "中途截断无任何完整对象') == [], "无完整对象宁可返回空"
    assert parse_claims_json('{"claim": "不是数组"') == []


def test_max_output_tokens_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("CORPUS_LLM_MAX_TOKENS", raising=False)
    assert max_output_tokens() == claims_mod.DEFAULT_MAX_OUTPUT_TOKENS == 4096
    monkeypatch.setenv("CORPUS_LLM_MAX_TOKENS", " 2048 ")
    assert max_output_tokens() == 2048
    monkeypatch.setenv("CORPUS_LLM_MAX_TOKENS", "abc")
    assert max_output_tokens() == 4096, "非法配置回退默认，不得崩溃"


def test_thinking_disabled_by_default_and_opt_in(monkeypatch) -> None:
    """max_tokens 是思考+回答共享预算：默认必须关思考，否则推理模型烧光预算（实测 0 条）。"""
    monkeypatch.delenv("CORPUS_LLM_THINKING", raising=False)
    assert claims_mod.thinking_extra_body() == {"thinking": {"type": "disabled"}}
    monkeypatch.setenv("CORPUS_LLM_THINKING", "ENABLED")
    assert claims_mod.thinking_extra_body() == {}, "显式打开时不附带参数，保持供应商默认"


def test_commit_block_with_mixed_null_and_str_periods(fresh_svc) -> None:
    """同块内同 metric 的 period 混有 NULL 与字符串（表格块常见）：
    去重三元组排序不得 TypeError —— P4 真实验收时踩出的 P3 隐性 bug。
    """
    payload = json.dumps(
        [
            {
                "claim": "利润表.其他收入 2026E (325)",
                "kind": "fact",
                "tickers": [],
                "metric": "利润表.其他收入",
                "value": "(325)",
                "period": "2026E",
            },
            {
                "claim": "利润表.其他收入 (317)",
                "kind": "fact",
                "tickers": [],
                "metric": "利润表.其他收入",
                "value": "(317)",
                "period": None,
            },
        ],
        ensure_ascii=False,
    )

    stats = fresh_svc.extract_legacy_claims(
        llm=lambda prompt: payload, retry_attempts=1, sleep_between=0
    )
    assert stats.failed == 0, stats.as_dict()
    rows = fresh_svc.legacy_claims_of(limit=100)
    assert {(r["metric"], r["period"]) for r in rows} == {
        ("利润表.其他收入", "2026E"),
        ("利润表.其他收入", None),
    }, "两种坐标都要落库（NULL period 与具体期间不算重复）"
