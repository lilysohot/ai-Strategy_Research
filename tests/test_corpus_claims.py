"""D2 验收：claim / entities 抽取。

覆盖：分级（省 LLM 调用）、LLM 输出容错、字段清洗、**可溯源（locator）**、
端到端落库与查询、幂等重跑、单块失败不中断。

另有一组「钱不能白花」的验收（见文件末尾）：**逐块落库**、**中断/失败后已完成块
不丢**、**重跑跳过已标记的块（含抽出 0 条的）**、**换模型/改 prompt 自动失效重抽
并整块替换**、**连续失败熔断**、**死信不再重试**。

隔离方式与 ``test_corpus_a1_ingest_search.py`` 一致：临时 schema，PG 不可用则 skip。
LLM 全程**注入假实现**，不发真实请求。
"""

from __future__ import annotations

import json
import textwrap
import uuid
from urllib.parse import quote

import psycopg
import pytest

from plugins.corpus.claims import (
    BlockView,
    claims_from_payload,
    extract_from_block,
    has_signal,
    parse_claims_json,
    triage_blocks,
    with_retry,
)
from plugins.corpus.service import CorpusService, dsn

SCRATCH_SCHEMA = "corpus_d2check"

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


def _scratch_url(admin: str, schema: str = SCRATCH_SCHEMA) -> str:
    options = quote(f"-c search_path={schema},public")
    sep = "&" if "?" in admin else "?"
    return f"{admin}{sep}options={options}"


@pytest.fixture(scope="module")
def scratch_dsn():
    admin = dsn()
    try:
        psycopg.connect(admin, connect_timeout=5).close()
    except psycopg.OperationalError as exc:  # pragma: no cover - 环境相关
        pytest.skip(f"PG 不可用，跳过 D2 测试：{exc}")

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')
        conn.execute(f'CREATE SCHEMA "{SCRATCH_SCHEMA}"')
    try:
        yield _scratch_url(admin, SCRATCH_SCHEMA)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')


@pytest.fixture(scope="module")
def tiny_corpus(tmp_path_factory):
    directory = tmp_path_factory.mktemp("d2_corpus")
    (directory / "2026-09-09_D2抽取验证.md").write_text(
        textwrap.dedent(
            """
            # D2 抽取验证

            贵州茅台 2026H1 营业收入约 1741 亿元，同比增长 1.3%。
            目标价 1888 元，维持增持评级。

            免责声明：本报告未经书面许可不得转载。
            """
        ).strip(),
        encoding="utf-8",
    )
    return directory


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


# ── 端到端（临时 schema） ──────────────────────────────────────
def test_end_to_end_extract_and_query(scratch_dsn, tiny_corpus) -> None:
    svc = CorpusService(scratch_dsn)
    svc.init_db()
    ingest = svc.ingest_dir(tiny_corpus)
    assert ingest.added >= 1, ingest.as_dict()

    stats = svc.extract_claims(llm=lambda prompt: FAKE_RESPONSE)

    assert stats.failed == 0, stats.as_dict()
    assert stats.claims == 2, stats.as_dict()
    assert stats.skipped_no_signal >= 0

    # ① 可按标的查（D3 挖掘 / D4 共识度的入口）
    by_ticker = svc.claims_of(ticker="600519.SH")
    assert len(by_ticker) == 2
    assert all("600519.SH" in row["tickers"] for row in by_ticker)

    # ② 可按类型查（fact / forecast）
    assert len(svc.claims_of(kind="forecast")) == 1
    assert len(svc.claims_of(kind="fact")) == 1

    # ③ locator 与 blocks 对齐 ⇒ claim 可溯源回原文
    for row in by_ticker:
        fetched = svc.fetch(row["doc_id"], row["locator"])
        assert fetched is not None, "claim 的 locator 必须能取回原文块"


def test_extract_is_idempotent(scratch_dsn, tiny_corpus) -> None:
    """重跑不得重复入库（UNIQUE + ON CONFLICT DO NOTHING）。"""
    svc = CorpusService(scratch_dsn)
    before = len(svc.claims_of(limit=100))
    svc.extract_claims(llm=lambda prompt: FAKE_RESPONSE)
    after = len(svc.claims_of(limit=100))
    assert after == before, "重跑抽取产生了重复 claim"


def test_single_block_failure_does_not_stop_batch(scratch_dsn, tiny_corpus) -> None:
    """LLM 单块失败只记 failure，不得中断整批（与 ingest 同一条纪律）。"""

    def flaky_llm(prompt: str) -> str:
        raise RuntimeError("LLM 超时")

    svc = CorpusService(scratch_dsn)
    # skip_existing=False：本测试要验证「LLM 失败也记 failure 不中断」，
    # 但同一 scratch 库里前面的测试已抽取过这些块 —— 不关掉断点续跑，
    # 它们会被直接跳过，failed 恒为 0，验证就失效了。
    stats = svc.extract_claims(llm=flaky_llm, retry_attempts=1, skip_existing=False)

    assert stats.failed >= 1, stats.as_dict()
    assert stats.failures, "失败必须带 locator 与原因，便于重试"
    assert "locator" in stats.failures[0]


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
    (1, "1", "贵州茅台 2026H1 营业收入 1741 亿元，同比增长 1.3%"),
    (2, "2", "目标价 1888 元，维持增持评级"),
    (3, "3", "2026H1 毛利率 90.8%，同比提升 0.5 个百分点"),
)


def _claim_json(text: str) -> str:
    return json.dumps(
        [
            {
                "claim": text,
                "kind": "fact",
                "tickers": [],
                "metric": "营业收入",
                "value": "1741 亿元",
                "period": "2026H1",
                "confidence": 0.9,
            }
        ],
        ensure_ascii=False,
    )


@pytest.fixture
def fresh_svc(tmp_path):
    """独立 schema + 独立文档的 ``CorpusService``：用例之间零共享状态。

    不走 ``ingest_dir``（切块规则会变，拿不稳"到底几个候选块"），直接写
    ``documents`` / ``blocks``，保证恰好 :data:`COMMIT_BLOCKS` 个候选块。
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
                    " status, char_count, block_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        COMMIT_DOC,
                        "D2 落库验证",
                        "data/corpus/d2commit.md",
                        uuid.uuid4().hex,
                        "text/markdown",
                        "ok",
                        90,
                        len(COMMIT_BLOCKS),
                    ),
                )
                cur.executemany(
                    "INSERT INTO blocks (doc_id, seq, locator, text) VALUES (%s,%s,%s,%s)",
                    [(COMMIT_DOC, seq, locator, text) for seq, locator, text in COMMIT_BLOCKS],
                )
            conn.commit()
        yield svc
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


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

    stats = fresh_svc.extract_claims(
        llm=llm,
        retry_attempts=1,
        sleep_between=0,
        max_consecutive_failures=0,
    )

    assert stats.failed >= 1, stats.as_dict()
    texts = [str(row["claim_text"]) for row in fresh_svc.claims_of(limit=100)]
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

    stats = fresh_svc.extract_claims(
        llm=llm,
        retry_attempts=1,
        sleep_between=0,
        should_stop=lambda: seen["n"] >= 1,  # 做完第 1 块就等于"收到信号"
    )

    assert stats.stopped_early is True
    assert stats.stopped_reason, "提前退出必须说明原因"
    assert seen["n"] == 1, "中断后不该再调模型"
    rows = fresh_svc.claims_of(limit=100)
    assert len(rows) == 1 and "第 1 块已落库" in str(rows[0]["claim_text"])


def test_rerun_skips_blocks_that_yielded_zero_claims(fresh_svc) -> None:
    """「抽出 0 条 claim」的块也算做过 —— 否则每次重跑都要为它再烧一次钱。"""
    calls = {"n": 0}

    def empty_llm(prompt: str) -> str:
        calls["n"] += 1
        return "[]"

    first = fresh_svc.extract_claims(llm=empty_llm, retry_attempts=1, sleep_between=0)
    assert first.candidates == len(COMMIT_BLOCKS) and first.claims == 0
    assert calls["n"] == len(COMMIT_BLOCKS)

    calls["n"] = 0
    second = fresh_svc.extract_claims(llm=empty_llm, retry_attempts=1, sleep_between=0)

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

    first = fresh_svc.extract_claims(
        llm=flaky,
        retry_attempts=1,
        sleep_between=0,
        max_consecutive_failures=0,
    )
    assert first.failed == len(COMMIT_BLOCKS)

    second = fresh_svc.extract_claims(
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
    """
    old_claims = fresh_svc.extract_claims(
        llm=lambda prompt: _claim_json("GLM-4.7 口径 1741 亿元"),
        retry_attempts=1,
        sleep_between=0,
    )
    assert old_claims.claims == len(COMMIT_BLOCKS)

    monkeypatch.setattr("plugins.corpus.service.EXTRACTOR_VERSION", "v2-test")
    new_claims = fresh_svc.extract_claims(
        llm=lambda prompt: _claim_json("AirX 口径 1741 亿元"),
        retry_attempts=1,
        sleep_between=0,
    )

    assert new_claims.claims == len(COMMIT_BLOCKS), "指纹变了却没重抽 —— 换模型会静默失效"
    texts = [str(row["claim_text"]) for row in fresh_svc.claims_of(limit=100)]
    assert sum("AirX 口径" in text for text in texts) == len(COMMIT_BLOCKS)
    assert not any("GLM-4.7 口径" in text for text in texts), "两代模型的结果混在一张表里"


def test_circuit_breaker_stops_after_consecutive_failures(fresh_svc) -> None:
    """额度耗尽 / 429 风控时必须熔断退出，不能继续把剩下的额度烧在重试上。"""
    calls = {"n": 0}

    def always_429(prompt: str) -> str:
        calls["n"] += 1
        raise RuntimeError("429 Too Many Requests")

    stats = fresh_svc.extract_claims(
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
        return fresh_svc.extract_claims(
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
