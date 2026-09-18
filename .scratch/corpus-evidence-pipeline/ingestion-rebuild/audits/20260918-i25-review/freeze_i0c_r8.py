"""生成 i0c-r8 冻结修订（RM-11：整改后重冻当前版本）。

绑定本批次改动/新增的实现、测试、文档与冻结验证器，并登记 RM-1～RM-13 整改说明。
**不覆盖历史快照**：i0c-r8.json 与 manifest 条目均 write-once，重复执行直接失败。

用法（仓库根）：
    .venv/bin/python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i25-review/freeze_i0c_r8.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# .../FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/<audit>/<file>
ROOT = Path(__file__).resolve().parents[5]
FREEZES = ROOT / ".scratch" / "corpus-evidence-pipeline" / "ingestion-rebuild" / "freezes"
AUDIT_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i25-review"

BINDING: dict[str, tuple[str, ...]] = {
    "implementation": (
        "plugins/corpus/preparation/engine.py",
        "plugins/corpus/preparation/repository.py",
        "plugins/corpus/preparation/repository_pg.py",
        "plugins/corpus/preparation/chunk.py",
    ),
    "tests": (
        "tests/test_corpus_preparation_publication_pg.py",
        "tests/test_corpus_preparation_contract.py",
    ),
    "freeze_validator": (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
    ),
    "docs": (
        "docs/plan/claims-market-closed-loop-plan.md",
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
    ),
}

CORRECTIONS: dict[str, str] = {
    "RM-1": (
        "finish_job 终态短路先于所有权校验（P1）：PG 与 Memory 两侧均改为**先锚定所有权**"
        "（fence_token 唯一绑定 attempt）再判终态——不一致即 lease_lost，一致才是合法重放。"
        "修复前接管者完成 attempt N+1 后，旧 worker 携 attempt N 旧 token finish 被误认成功。"
    ),
    "RM-2": (
        "发布指针已切、PUBLISHED 终态未提交即断线（P1）：新增 engine._reconcile_published_job，"
        "在幂等短路返回前补齐终态。采用**受 fencing 保护的幂等恢复**（非合并事务）："
        "先用当前行租约提交，因过期被拒则重新取租约后提交，租约仍被他人持有（未过期）时不抢占。"
    ),
    "RM-3": (
        "引擎成功短路绕过当前准入（P1）：新增 engine._verify_admission_still_current，"
        "区分「查询历史发布结果」（可短路）与「请求当前有效发布」（短路前须核验 build 绑定的"
        "决定仍是来源当前决定且仍 in_scope）。拒绝抛 StoreError，与 Store.publish 事务内同情形"
        "拒绝同族，消除 Store 门与入口行为不一致。"
    ),
    "RM-4": (
        "双 Adapter fencing 判据次序统一（P2）：repository.py 三处（_require_stage_ownership、"
        "_require_publication_ownership、_fence）由「状态优先」改为「凭据优先」，与 PgStore 一致；"
        "两侧「租约已过期」消息统一含 lease_lost 语义。新增双 Adapter 对称回归用例断言同一错误语义。"
    ),
    "RM-5": (
        "续租正向路径（P2）：新增 test_heartbeat_renews_lease_and_expired_renewal_is_refused——"
        "此前全仓 heartbeat 测试仅 2 处且均为失败路径。断言 lease_until 前移、heartbeat_at 更新、"
        "不换 token、不消耗 attempt 预算；过期后不得原地续命。SHORT_LEASE=(ttl=3, heartbeat=1)"
        "满足 I0C-2 的 heartbeat ≤ TTL/3。"
    ),
    "RM-6": (
        "连接断开场景（P2，架构 §8.1 明列）：新增 "
        "test_disconnect_before_finish_leave_no_half_commit_and_recovers——区别于「提交响应丢失」"
        "的重放。验证无半提交、撕裂态可补齐、恢复后指针与 generation 不漂移。"
    ),
    "RM-7": (
        "准入更新纳入发布互斥（P2）：repository_pg.put_admission 事务首语句取 "
        "pg_advisory_xact_lock(pub_ns, source_id)，与 publish/retire 同一临界区，"
        "消除「publish 校验过 current_decision_id 后、另一连接并发移动指针」的交错窗口。"
    ),
    "RM-8": (
        "引擎级恢复验收（P2）：新增 test_engine_publish_reconciles_unfinished_job_after_disconnect，"
        "经正式 publish_build 与 _verify_publication_ready（PARSED/CHUNKED 阶段门）而非 "
        "_publish_chain 直操作 Store；断言补齐了 PUBLISHED 终态。底层并发用例保留。"
    ),
    "RM-10": (
        "chunk_rev 与索引文本规则联动（P3）：明确 search_text 规则**由 index_rev 独立表达**、"
        "不随 chunk_rev 绑定（前者只改 token 形态、后者改块边界，影响面不同），"
        "修正 engine.py 中「随 chunk_rev 绑定」的注释；CHUNK_REV 保持 chunk-2，避免无谓全量重建。"
    ),
    "RM-11": "收口：新建本冻结修订 i0c-r8（parent=i0c-r7），绑定当前实现/测试/文档与冻结验证器。",
    "RM-12": (
        "收口：按 tasks.md §0 纪律回填总计划台账与任务清单——复核链接、F1—F3 现状、"
        "I2-5 整改闭环、M5 维持 not_declared、本清单链接。"
    ),
    "RM-13": (
        "F4「冻结与工作区不一致」经 2026-09-18 核验已自愈（i0c-r7 绑定当前文档字节，"
        "validate_i0c_freeze.py exit 0），登记关闭，不改历史快照。"
    ),
}

NOTES: list[str] = [
    "i0c-r7 及更早快照保留历史字节，不追改；本修订登记 2026-09-18 I2-5 独立复核整改（RM-1～RM-13）。",
    "绑定为当前最新状态（本批次改动/新增路径实时重算），由 validate_i0c_freeze.py 按 "
    "latest-revision-wins 合并为 i0c-current 后逐一核验。",
    "证据：审核探针由 4 failed/1 passed 转为 5 passed；真库门 publication_pg + repository_pg "
    "35 passed 零 skip；普通环境 preparation 214 passed/2 skipped；i1 守卫 env 业务 12 文件 "
    "195 passed；守卫自检 19 项按 M4 口径在普通环境 19 passed；ruff/pyright/import_smoke 全绿。",
    "RM-9（测试卫生：daemon 线程与 statement_timeout）为 P3 且不阻断 I2-5，未在本次批次实施，"
    "留待后续批次；已确认其不改变功能语义。",
    "M5 仍 not_declared；生产库 I4 前零写入；I2-8/I2-4/I2-6 未完成。",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    r7 = FREEZES / "i0c-r7.json"
    if not r7.is_file():
        raise SystemExit(f"缺少父快照：{r7}")

    binding: dict[str, dict[str, str]] = {}
    for group, rels in BINDING.items():
        binding[group] = {}
        for rel in rels:
            target = ROOT / rel
            if not target.is_file():
                raise SystemExit(f"待绑定文件缺失：{rel}")
            binding[group][rel] = digest(target)

    snapshot = {
        "snapshot_id": "i0c-r8",
        "revision": "r8",
        "phase": "i0c",
        "task": (
            "I2-5 independent review remediation (audits/20260918-i25-review): "
            "RM-1 finish terminal ownership anchor, RM-2 published-job reconciliation on "
            "short-circuit, RM-3 admission-current check on engine short-circuit, "
            "RM-4 fencing order parity across adapters, RM-5 heartbeat renewal coverage, "
            "RM-6 disconnect recovery, RM-7 admission mutex (source advisory lock), "
            "RM-8 engine-level recovery via VERIFIED gate, RM-10 chunk_rev/index_rev semantics"
        ),
        "binding": binding,
        "corrections": CORRECTIONS,
        "notes": NOTES,
        "m5_declaration": (
            "not_declared（I2-1/I2-2/I2-3/I2-5/I2-7 完成；仍需 I2-8/I2-4/I2-6）"
        ),
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "parent_snapshot": {
            "snapshot_id": "i0c-r7",
            "path": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i0c-r7.json",
            "sha256": digest(r7),
        },
    }

    out = FREEZES / "i0c-r8.json"
    if out.exists():
        raise SystemExit(f"{out} 已存在（write-once：不得覆盖历史快照）")
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {out}")

    manifest_path = FREEZES / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshots = manifest.setdefault("snapshots", [])
    if any(entry.get("snapshot_id") == "i0c-r8" for entry in snapshots):
        raise SystemExit("manifest 已含 i0c-r8 条目（write-once）")
    snapshots.append(
        {
            "snapshot_id": "i0c-r8",
            "file": "i0c-r8.json",
            "sha256": digest(out),
            "parent_snapshot_id": "i0c-r7",
            "created_at": snapshot["created_at"],
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已更新 {manifest_path}（条目 {len(snapshots)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
