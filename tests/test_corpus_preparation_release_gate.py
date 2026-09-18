"""发布门 / scope / 执行生命周期常驻回归（full-review C1/C2/C6 转正副本）。

审计原件见
``.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-full-review/test_chain_contracts.py``
（write-once，不修改）。本文件把其中的端到端契约固化为 tests/ 常驻回归：

- C1 发布门：质量缺口拒绝发布；quality_report 必须存在且形状恰为两键；幂等
  重放不递增 generation。
- C2 scope：批准范围约束 units/chunks（范围外文本不得进入检索投影）；locator
  无法解释或产生空 build 一律 fail-closed，不降级全篇。
- C6 生命周期：取消提交 CANCELLED 并阻断后继阶段（取消的 build 不自动复活）；
  解析检查点落盘并在重试中复用（reader 只调用一次）。

全部为合成输入，零模型、零网络、无 PG。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
    UnitStatus,
    source_id_from_bytes,
)
from plugins.corpus.preparation.engine import (
    EngineCancelled,
    EngineError,
    PlanEntry,
    execute_builds,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.repository import MemoryStore, StoreError

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
POLICY = AdmissionPolicy(POLICY_REV_V1, tuple(ResearchDomain))
LEASE = LeaseConfig(300, 60, 600, 3)
NORMAL = "# 证券公司研究\n\nApproved section.\n\nOutside approved scope: 987654.\n"


def _make_store_and_source(
    tmp_path: Path, text: str = NORMAL, *, name: str = "report.md", scope: str | None = None
) -> tuple[MemoryStore, Path, str]:
    store = MemoryStore(clock=lambda: NOW)
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    sid = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(
        ReviewedDecision(
            "r1",
            sid,
            "reviewer",
            NOW,
            ReviewDecision.ADMITTED,
            "synthetic approval",
            scope_ref=scope,
            locators=(scope,) if scope else (),
        )
    )
    return store, path, sid


def _execute(
    store: MemoryStore,
    tmp_path: Path,
    path: Path,
    *,
    reader=read_document,
    cancel_check=None,
):
    plan = plan_builds(
        [PlanEntry(str(path), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("r1",))],
        policy=POLICY,
    )
    return execute_builds(
        store,
        plan,
        policy=POLICY,
        archive_root=tmp_path / "archive",
        owner_id="gate",
        now=NOW,
        lease=LEASE,
        reader=reader,
        cancel_check=cancel_check,
    ).outcomes[0]


def _capture_builds(store: MemoryStore) -> list[Build]:
    """捕获引擎 put_build 的 build（execute 抛错时无 outcome 可取）。"""
    captured: list[Build] = []
    original_put_build = store.put_build

    def capture(build: Build):
        captured.append(build)
        return original_put_build(build)

    store.put_build = capture  # type: ignore[method-assign]
    return captured


# --- C1：发布门 ---


def _write_gap_pdf(path: Path) -> None:
    """有文字层 + 大面积图片区域的 PDF（image_only_page 缺口，OCR 语义）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Readable title", fontsize=11)
    page.insert_image(
        pymupdf.Rect(72, 100, 520, 700),
        pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10)),
    )
    doc.save(str(path))
    doc.close()


def test_quality_gap_blocks_publication(tmp_path: Path) -> None:
    path = tmp_path / "证券公司研究.pdf"
    _write_gap_pdf(path)
    store = MemoryStore(clock=lambda: NOW)
    sid = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(
        ReviewedDecision("r1", sid, "reviewer", NOW, ReviewDecision.ADMITTED, "approval")
    )
    outcome = _execute(store, tmp_path, path)
    assert outcome.build is not None
    quality = json.loads(outcome.build.quality_report)
    assert any(
        "image_only_page" in gap or "image_region_unreadable" in gap
        for gap in quality["gap_regions"]
    )
    with pytest.raises((EngineError, StoreError)):
        publish_build(store, outcome.build.build_id, activated_at=NOW)


class _TamperStore(MemoryStore):
    """put_build 直写（绕过幂等冲突检查）——仅用于注入畸形 quality_report。"""

    def put_build(self, build: Build) -> None:
        self._builds[build.build_id] = build


def _mark_stages_succeeded(store: MemoryStore, build_id: str) -> None:
    """把 PARSED/CHUNKED 置为 SUCCEEDED，隔离出 quality_report 这一道门。"""
    for stage in (JobStage.PARSED, JobStage.CHUNKED):
        store.register_job(build_id, stage)
        job = store.acquire_job(build_id, stage, "gate", NOW, LEASE)
        store.finish_job(build_id, stage, "gate", job.fence_token, NOW, JobState.SUCCEEDED)


def _reput_build_with_quality(build: Build, store: MemoryStore, quality: str) -> None:
    store.put_build(
        Build(
            build_id=build.build_id,
            source_id=build.source_id,
            decision_id=build.decision_id,
            parse_rev=build.parse_rev,
            clean_rev=build.clean_rev,
            chunk_rev=build.chunk_rev,
            index_rev=build.index_rev,
            scope_ref=build.scope_ref,
            quality_report=quality,
        )
    )


def test_quality_report_must_exist_with_exact_shape(tmp_path: Path) -> None:
    store = _TamperStore(clock=lambda: NOW)
    path = tmp_path / "report.md"
    path.write_text(NORMAL, encoding="utf-8")
    sid = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(
        ReviewedDecision("r1", sid, "reviewer", NOW, ReviewDecision.ADMITTED, "approval")
    )
    plan = plan_builds(
        [PlanEntry(str(path), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("r1",))],
        policy=POLICY,
    )
    outcome = execute_builds(
        store,
        plan,
        policy=POLICY,
        archive_root=tmp_path / "archive",
        owner_id="gate",
        now=NOW,
        lease=LEASE,
    ).outcomes[0]
    assert outcome.build is not None
    build_id = outcome.build.build_id
    _mark_stages_succeeded(store, build_id)

    for bad_quality in (
        "",  # 缺质量台账：不得靠 or "{}" 旁路
        "{}",  # 形状非法：必须恰为 gap_regions/oversized_chunks 两键
        json.dumps({"gap_regions": [], "oversized": []}),  # 键名漂移
    ):
        _reput_build_with_quality(outcome.build, store, bad_quality)
        with pytest.raises((EngineError, StoreError)):
            publish_build(store, build_id, activated_at=NOW)


def test_publish_idempotent_replay_and_generation(tmp_path: Path) -> None:
    store, path, _ = _make_store_and_source(tmp_path)
    outcome = _execute(store, tmp_path, path)
    assert outcome.build is not None
    first = publish_build(store, outcome.build.build_id, activated_at=NOW)
    replay = publish_build(store, outcome.build.build_id, activated_at=NOW)
    assert replay == first and first.generation == 1  # 幂等重放不递增 generation
    lost_response = publish_build(store, outcome.build.build_id, activated_at=NOW + timedelta(seconds=1))
    # publish_idempotency_v2（I0-C 裁决）：幂等按目标状态比对，不以时间为键——
    # 响应丢失+时钟前进的重试恒返回已提交结果。
    assert lost_response == first and lost_response.generation == 1
    assert lost_response.activated_at == first.activated_at  # 时间不刷新


# --- C2：scope 闭合 ---


def test_scoped_approval_bounds_units_and_chunks(tmp_path: Path) -> None:
    # The approved boundary ends at the complete second unit.  A boundary
    # through the next unit is rejected rather than silently dropping its
    # approved prefix.
    store, path, _ = _make_store_and_source(tmp_path, scope="char:0-27")
    outcome = _execute(store, tmp_path, path)
    assert outcome.build is not None
    build_id = outcome.build.build_id
    units = store.get_units(build_id)
    out_of_scope = [u for u in units if u.status is UnitStatus.OUT_OF_SCOPE]
    assert out_of_scope, "范围外单元必须显式标 out_of_scope"
    assert any("987654" in u.raw_text for u in out_of_scope)
    for chunk in store.get_chunks(build_id):
        assert "987654" not in chunk.search_text  # 检索投影受批准范围限制
    publication = publish_build(store, build_id, activated_at=NOW)
    assert publication.active_build_id == build_id


def test_unparsable_or_empty_scope_fails_closed(tmp_path: Path) -> None:
    # locator 前缀无法解释 → EngineError，不降级为全篇构建。
    store, path, _ = _make_store_and_source(tmp_path, scope="page:1")
    with pytest.raises(EngineError):
        _execute(store, tmp_path, path)
    # 范围不覆盖任何保留区域（空 build）→ EngineError，fail-closed。
    store2, path2, _ = _make_store_and_source(tmp_path, scope="char:900-999", name="report2.md")
    with pytest.raises(EngineError):
        _execute(store2, tmp_path, path2)


@pytest.mark.parametrize("scope", [" ", ",", " , "])
def test_nonempty_invalid_scope_never_means_full_document(tmp_path: Path, scope: str) -> None:
    store, path, _ = _make_store_and_source(tmp_path, scope=scope)
    with pytest.raises(EngineError, match="未包含任何有效"):
        _execute(store, tmp_path, path)


def test_partially_overlapping_scope_is_rejected_not_silently_shrunk(tmp_path: Path) -> None:
    # The second paragraph starts in scope but extends beyond it.  Publishing
    # only the heading would hide approved content, so an unaligned range is
    # not a complete scoped build.
    store, path, _ = _make_store_and_source(tmp_path, scope="char:0-18")
    with pytest.raises(EngineError, match="未与读取单元边界对齐"):
        _execute(store, tmp_path, path)


# --- C6：执行生命周期 ---


def test_preexisting_cancel_stops_before_reader_or_build(tmp_path: Path) -> None:
    store, path, _ = _make_store_and_source(tmp_path)
    captured = _capture_builds(store)
    with pytest.raises(EngineCancelled):
        _execute(store, tmp_path, path, cancel_check=lambda: True)
    # Admission depends on parsing, so a pre-existing cancellation now stops
    # before that expensive operation and before a build can truthfully exist.
    assert captured == []
    assert store.get_source_checkpoint(source_id_from_bytes(path.read_bytes()), "parse") is None


def test_parse_checkpoint_written_and_reused_on_retry(tmp_path: Path) -> None:
    store, path, sid = _make_store_and_source(tmp_path)
    reads: list[Path] = []

    def spy_reader(archived: Path):
        reads.append(archived)
        return read_document(archived)

    first = _execute(store, tmp_path, path, reader=spy_reader)
    assert first.build is not None
    checkpoint = store.get_source_checkpoint(sid, "parse")
    assert checkpoint is not None
    data = json.loads(checkpoint)
    assert data["source_id"] == sid
    assert data["reparse_reason"] == "checkpoint_absent"  # 重算原因落盘
    assert data["extractor_rev"]
    second = _execute(store, tmp_path, path, reader=spy_reader)
    assert second.build is not None
    assert len(reads) == 1, "有效检查点必须复用，重试不得重读原文"


def test_checkpoint_semantic_damage_reparses_and_keeps_quality_gate(tmp_path: Path) -> None:
    path = tmp_path / "gap.pdf"
    _write_gap_pdf(path)
    store = MemoryStore(clock=lambda: NOW)
    sid = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(
        ReviewedDecision("r1", sid, "reviewer", NOW, ReviewDecision.ADMITTED, "approval")
    )
    first = _execute(store, tmp_path, path)
    assert first.build is not None
    checkpoint = json.loads(store.get_source_checkpoint(sid, "parse"))
    checkpoint["issues"] = []  # text hashes remain unchanged: semantic hash must catch this.
    store.put_source_checkpoint(sid, "parse", json.dumps(checkpoint))

    repaired = _execute(store, tmp_path, path)
    assert repaired.build is not None
    with pytest.raises((EngineError, StoreError), match="质量缺口"):
        publish_build(store, repaired.build.build_id, activated_at=NOW)
