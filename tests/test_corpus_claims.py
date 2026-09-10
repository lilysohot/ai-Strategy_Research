"""D2 验收：claim / entities 抽取。

覆盖：分级（省 LLM 调用）、LLM 输出容错、字段清洗、**可溯源（locator）**、
端到端落库与查询、幂等重跑、单块失败不中断。

隔离方式与 ``test_corpus_a1_ingest_search.py`` 一致：临时 schema，PG 不可用则 skip。
LLM 全程**注入假实现**，不发真实请求。
"""

from __future__ import annotations

import json
import textwrap
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


def _scratch_url(admin: str) -> str:
    options = quote(f"-c search_path={SCRATCH_SCHEMA},public")
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
        yield _scratch_url(admin)
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
            {"claim": "目标价 1888 元", "kind": "瞎写的", "tickers": ["600519.SH", ""], "confidence": 1.7},
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
    stats = svc.extract_claims(llm=flaky_llm, retry_attempts=1)

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
