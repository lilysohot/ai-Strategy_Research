"""I0-C 发布幂等协议 v2 探针（publish_idempotency_v2，design-review G2 闭合验证）。

现行探针（I0-C 阶段新增）；历史口径说明：20260916-i1-9-retest/test_i1_9_acceptance.py
的 ``test_control_clean_md_can_exercise_generation_independently`` 断言『同 build 不同
activated_at → generation 递增』属历史口径（R1 三元组比较），在 v2 状态比对协议下按
历史记录处理（预期失败节点），历史文件不改写。

协议（design-review.json i0c_1_protocol.publish_idempotency_v2）：
- 幂等按目标状态 ``(current_decision_id, active_build_id)`` 比对，不以时间为键；
- 指针翻转时 generation+1、时间取翻转事务（内存注入时钟 / PG 数据库时间）；
- generation 语义 = 活动指针变更次数。
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from plugins.corpus.preparation.admission import POLICY_REV_V1, AdmissionPolicy
from plugins.corpus.preparation.contract import (
    JobStage,
    LeaseConfig,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
    source_id_from_bytes,
)
from plugins.corpus.preparation.engine import PlanEntry, execute_builds, plan_builds, publish_build
from plugins.corpus.preparation.repository import MemoryStore

ROOT = Path(__file__).resolve().parents[5]
FIXTURES = ROOT / "tests/fixtures/corpus_preparation"
NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)
POLICY = AdmissionPolicy(POLICY_REV_V1, tuple(ResearchDomain))
LEASE = LeaseConfig(300, 60, 600, 3)


def _prepare_md(tmp_path: Path) -> tuple[MemoryStore, str]:
    path = FIXTURES / "synthetic-company-report.md"
    store = MemoryStore(clock=lambda: NOW)
    source_id = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(
        ReviewedDecision(
            "r1", source_id, "synthetic-reviewer", NOW,
            ReviewDecision.ADMITTED, "synthetic whole-source admission, no quality waiver",
        )
    )
    plan = plan_builds(
        [PlanEntry(str(path), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("r1",))],
        policy=POLICY,
    )
    outcome = execute_builds(
        store, plan, policy=POLICY, archive_root=tmp_path / "archive",
        owner_id="i0c-protocol-probe", now=NOW, lease=LEASE,
    ).outcomes[0]
    assert outcome.build is not None
    quality = json.loads(outcome.build.quality_report)
    assert quality == {"gap_regions": [], "oversized_chunks": []}
    return store, outcome.build.build_id


def test_same_state_replay_idempotent_regardless_of_time(tmp_path: Path) -> None:
    """同 (决定, build) 重放：无论时间是否前进（响应丢失场景）恒幂等。"""
    store, build_id = _prepare_md(tmp_path)
    first = publish_build(store, build_id, activated_at=NOW)
    assert first.generation == 1
    replay = publish_build(store, build_id, activated_at=NOW)
    assert replay == first
    lost_response = publish_build(store, build_id, activated_at=NOW + timedelta(hours=1))
    assert lost_response == first and lost_response.generation == 1
    assert lost_response.activated_at == first.activated_at  # 时间不刷新


def test_lost_response_replay_after_reacquire_is_idempotent(tmp_path: Path) -> None:
    """G2 精确场景：响应丢失 → 重新 acquire PUBLISHED（新 attempt/token）→
    再发布：目标状态不变 → 恒幂等，不得误判新激活。"""
    store, build_id = _prepare_md(tmp_path)
    first = publish_build(store, build_id, activated_at=NOW)
    reacquired = store.acquire_job(
        build_id, JobStage.PUBLISHED, "i0c-protocol-probe",
        NOW + timedelta(seconds=1), LEASE,
    )
    assert reacquired.attempt >= 2  # PUBLISHED 重新 acquire 消耗 attempt 预算
    replay = store.publish(
        first.source_id, first.current_decision_id, build_id,
        NOW + timedelta(seconds=2),
        owner_id="i0c-protocol-probe", fence_token=reacquired.fence_token,
    )
    assert replay == first and replay.generation == 1
    assert replay.activated_at == first.activated_at


def test_state_change_increments_generation_time_from_flip_transaction(tmp_path: Path) -> None:
    """指针翻转才递增 generation；时间取翻转事务（内存=注入时钟，PG=DB now()）。"""
    store, build_id = _prepare_md(tmp_path)
    first = publish_build(store, build_id, activated_at=NOW)
    source_id, decision_id = first.source_id, first.current_decision_id

    store.retire(source_id, decision_id, NOW + timedelta(seconds=1))
    retired = store.get_publication(source_id)
    assert retired is not None and retired.active_build_id is None
    assert retired.generation == 2 and retired.activated_at == NOW + timedelta(seconds=1)

    republished = publish_build(store, build_id, activated_at=NOW + timedelta(seconds=2))
    assert republished.generation == 3 and republished.active_build_id == build_id
    assert republished.activated_at == NOW + timedelta(seconds=2)


def test_control_state_never_changes_without_flip(tmp_path: Path) -> None:
    """对照：连续三次发布（时间递增）generation 恒为 1——排除协议失效假阳性。"""
    store, build_id = _prepare_md(tmp_path)
    publications = [
        publish_build(store, build_id, activated_at=NOW + timedelta(seconds=i))
        for i in range(3)
    ]
    assert all(pub.generation == 1 for pub in publications)
    assert len({pub.activated_at for pub in publications}) == 1
