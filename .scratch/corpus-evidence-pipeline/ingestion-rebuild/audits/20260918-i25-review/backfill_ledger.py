"""I2-5 独立复核整改台账回填（RM-12）。

向总计划台账的 I2-5 行追加 2026-09-18 复核结论与整改链接，并在 I2-2 整改段之后
追加 I2-5 整改叙事段。历史内容追加不覆盖；脚本幂等（重复执行不重复插入）。

用法（仓库根）：
    .venv/bin/python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i25-review/backfill_ledger.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# .../FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/<audit>/<file>
# parents: 0=<audit> 1=audits 2=ingestion-rebuild 3=corpus-evidence-pipeline 4=.scratch 5=仓库根
ROOT = Path(__file__).resolve().parents[5]
LEDGER = ROOT / "docs/plan/claims-market-closed-loop-plan.md"
TASKS = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
AUDIT = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i25-review"

ROW_ADDITION = (
    "。**2026-09-18 独立复核"
    "（[review](../../{audit}/review.md)）"
    "判定“实现与首轮真库测试已交付、独立复核待整改”：探针 4 failed/1 passed，"
    "复现 F1（陈旧 token 迟到 finish 被误认幂等）、"
    "F2（指针已切、finish 前断线 → job 永久 RUNNING）、"
    "F3（引擎短路绕过当前准入）；同日按"
    "[整改清单](../../{audit}/remediation-checklist.md)"
    "完成 RM-1～RM-8、RM-10 闭环，"
    "详见 <a href=\"#i25-remediation\">I2-5 独立复核整改</a>**"
).format(audit=AUDIT)

NARRATIVE = f"""
<a id="i25-remediation"></a>

### 2026-09-18 I2-5 独立复核整改（RM-1～RM-12）

依据[独立复核](../../{AUDIT}/review.md)与[整改清单](../../{AUDIT}/remediation-checklist.md)。
复核判定 I2-5「实现与首轮真库测试已交付、独立复核待整改」：新增探针 **4 failed / 1 passed**，
复现 3 类功能缺口。本轮按批次完成整改，**探针转为 5 passed**。

**批次 A（代码缺陷，RM-1～RM-4）**

- **RM-1（P1）finish 终态短路先于所有权校验**：`repository_pg.finish_job` 与
  `repository.finish_job` 原先先判「当前行已是相同终态」再校验 owner/token，导致接管者完成
  attempt N+1 后，旧 worker 携 attempt N 的旧 token finish 被误认成功。改为**先锚定所有权**
  （fence_token 唯一绑定 attempt）再判终态：不一致即 `lease_lost`，一致才是合法重放。
- **RM-2（P1）指针已切、finish 未提交即断线**：新增 `engine._reconcile_published_job`，
  在幂等短路返回前补齐未闭合的 PUBLISHED 终态。采用**受 fencing 保护的幂等恢复**（非合并事务）：
  先用当前行租约提交；因过期被拒则重新取租约后提交；租约仍被他人持有（未过期）时**不抢占**。
  保持 Store Seam 职责（publish 管指针、finish_job 管 job 状态），不扩大 J1/J2 锁范围。
- **RM-3（P1）引擎短路绕过当前准入**：新增 `engine._verify_admission_still_current`，
  区分「查询历史发布结果」与「请求当前有效发布」——后者短路前须核验 build 绑定的决定仍是来源
  当前决定且仍 in_scope。拒绝抛 `StoreError`，与 `Store.publish` 事务内同情形拒绝**同族**。
- **RM-4（P2）双 Adapter fencing 次序统一**：`repository.py` 三处（`_require_stage_ownership`、
  `_require_publication_ownership`、`_fence`）由「状态优先」改为「凭据优先」，与 PgStore 一致；
  两侧「租约已过期」消息统一含 `lease_lost` 语义。新增双 Adapter **对称**回归用例，断言同一错误语义。

**批次 B（真 PG 补测，RM-5～RM-8）**

- **RM-5**：新增 `test_heartbeat_renews_lease_and_expired_renewal_is_refused`——续租正向路径
  （此前全仓零覆盖）：`lease_until` 前移、`heartbeat_at` 更新、不换 token、不消耗 attempt 预算；
  过期后不得原地续命。`SHORT_LEASE=(ttl=3, heartbeat=1)` 满足 I0C-2 的 heartbeat ≤ TTL/3。
- **RM-6**：新增 `test_disconnect_before_finish_leave_no_half_commit_and_recovers`——连接断开
  （区别于「提交响应丢失」的重放）：无半提交、撕裂态可补齐、恢复后指针/generation 不漂移。
- **RM-7**：`repository_pg.put_admission` 纳入 `_ADVISORY_PUB_NS` source 级临界区，
  与 publish/retire 同锁，消除「publish 校验过指针后、准入被并发移动」的交错窗口。
- **RM-8**：新增 `test_engine_publish_reconciles_unfinished_job_after_disconnect`——
  经正式 `publish_build` 与 `_verify_publication_ready`（PARSED/CHUNKED 阶段门）而非
  `_publish_chain` 直操作 Store；断言实际补齐了 PUBLISHED 终态。

**批次 C（收口，RM-10～RM-12）**

- **RM-10**：明确 search_text 规则**由 `index_rev` 独立表达**、不随 `chunk_rev` 绑定
  （前者只改 token 形态，后者改块边界，影响面不同），修正 engine.py 中「随 chunk_rev 绑定」
  的注释；`CHUNK_REV` 保持 chunk-2，避免无谓全量重建。
- **RM-11 / RM-12**：新建冻结修订 **i0c-r8**（parent=i0c-r7）绑定当前实现/测试/文档与验证器，
  并回填本台账与任务清单（本段）。

**验证证据**

- 审核探针：基线 **4 failed / 1 passed** → **5 passed**（i1 守卫 env，env -i）。
- 真库门（`i2_sandbox_corpus`，i2-sandbox 守卫 env）：`publication_pg + repository_pg`
  **35 passed、零 skip**（含新增 RM-4/RM-5/RM-6/RM-8 四例）。
- 普通环境：`tests/test_corpus_preparation_*.py` **214 passed / 2 skipped**
  （2 skipped 为需 CORPUS_I2_DSN 的 PG 套件，已由真库门实跑覆盖，非 skip 记通过）。
- i1 守卫 env 业务 12 文件 **195 passed**；守卫自检 19 项按 M4 口径在普通环境跑 **19 passed**
  （守卫测试不计入 env -i 矩阵：子进程在已装守卫时拒绝换配置重装）。
- 静态：`ruff check plugins/` All checks passed、`ruff format --check` 18 files ok、
  `pyright` 改动文件 **0 errors**、`import_smoke --stage 1` **356/356**。

**状态**：I2-5 整改闭环，满足整改清单 §5 的 DoD 1—3；状态与 M5 声明随 i0c-r8 冻结与
本回填一并更新。**M5 仍 not_declared**（尚缺 I2-8/I2-4/I2-6）；生产库 I4 前零写入。
"""


def backfill_ledger() -> bool:
    """在 I2-5 台账行尾追加复核结论；幂等。"""
    text = LEDGER.read_text(encoding="utf-8")
    if "i25-remediation" in text:
        print("台账已回填，跳过")
        return False
    lines = text.splitlines(keepends=True)
    anchor = "生产库 I4 前零写入"
    for index, line in enumerate(lines):
        if not line.startswith('| <a id="i2-5"></a>I2-5'):
            continue
        pos = line.rfind(anchor)
        if pos < 0:
            print("I2-5 行缺少锚点", file=sys.stderr)
            return False
        pos += len(anchor)
        lines[index] = line[:pos] + ROW_ADDITION + line[pos:]
        break
    else:
        print("未找到 I2-5 台账行", file=sys.stderr)
        return False

    # 叙事段插入到 I2-2 独立复核整改段之后
    marker = '<a id="i2-2-independent-remediation"></a>'
    for index, line in enumerate(lines):
        if line.strip() == marker:
            # 找到该段之后的空行位置（段末）
            cursor = index
            while cursor < len(lines) and not lines[cursor].startswith("| "):
                cursor += 1
            lines.insert(cursor, NARRATIVE)
            break
    else:
        print("未找到 I2-2 整改段锚点", file=sys.stderr)
        return False

    LEDGER.write_text("".join(lines), encoding="utf-8")
    print("台账回填完成")
    return True


def backfill_tasks() -> bool:
    """任务清单 §0 追加 0918 I2-5 复核结论。"""
    text = TASKS.read_text(encoding="utf-8")
    if "20260918-i25-review" in text:
        print("任务清单已回填，跳过")
        return False
    marker = "| I2-5 publication\\_pg |"
    addition = (
        "| I2-5 独立复核整改 | "
        "[0918 复核：F1—F3 未闭环 → RM-1～RM-12 整改闭环，探针 5 passed、真库 35 passed]"
        f"(../../{AUDIT}/review.md) |\n"
    )
    if marker not in text:
        print("任务清单缺少 I2-5 定位行锚点", file=sys.stderr)
        return False
    text = text.replace(marker + "\n", marker + "\n" + addition, 1)
    TASKS.write_text(text, encoding="utf-8")
    print("任务清单回填完成")
    return True


if __name__ == "__main__":
    changed = backfill_ledger()
    changed = backfill_tasks() or changed
    print("回填完成" if changed else "无变更")
