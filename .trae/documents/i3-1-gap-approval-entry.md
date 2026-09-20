# I3-1 缺口人工认可入口 — 实现计划

## Context

I3-1 三类开发 E2E 照 U 批准集（6 份 PDF）执行后判定未完成（i0c-r32）：13 处阻断缺口（`table_lines_without_extraction` 9 + `image_region_unreadable` 4）导致可发布仅 2/6（company 0/2、industry 1/2、macro 1/2），『三类每类≥2 份』在现行门 + 现行裁定下不可满足。

U 已裁定（2026-09-20）：

* **裁定① = 人工认可入口**：人工可视核验缺口内容后登记认可，使缺口从 blocking 转可发布但仍可见（借鉴 admission 人工凭证机制）。

* **裁定② = 格式覆盖先不动**：v1 有效声称格式保持 PDF，DOCX/MD 不声称，§12.1 声称修订挂起，本轮不做格式声称变更。

本轮目标：实现人工认可入口 + 落两项裁定记录 + 照批准集重跑（13 处缺口人工认可后预期 6/6 可发布，per\_class\_min\_2 满足）+ 冻结新修订 r34 + 台账回填。

## 关键既有事实（复用点）

* 缺口裁决 `plugins/corpus/preparation/gaps.py`：`DEFAULT_GAP_DISPOSITION`（L74-86）、`GapLifecycle`（L58-71，blocking/acknowledged/out\_of\_scope）、`gap_record()`（L210）、`blocking_gaps()`（L280，**发布门唯一判据**）、`acknowledged_gaps()`（L285）、`gap_summary()`（L290）、`recovery_paths()`（L302）。

* 发布门 `plugins/corpus/preparation/engine.py`：`gap_records_of(build)`（L1119）、`_verify_publication_ready`（L1148，blocking 拒绝发布）、`check_build_publishable`（L1237，与 publish 共用实现）、`_acknowledged_keys_of`（L1133）。

* 人工凭证模式 `admission.py`：`ReviewedDecision`（contract.py L367）+ `resolve_effective_decision`（L360）supersedes 链校验（decision\_id 唯一、断链/环 fail-closed，L264-310）。

* 存储层：`repository.py`（内存 `_reviewed` dict，L248）；`repository_pg.py`（corpus\_review\_decisions 表 upsert/select，L389-448）。

* CLI：`plugins/corpus/cli.py` `_HANDLERS`@L641、`main`@L654、`_GapView`@L172、`_precheck_entry`@L215；退出码 0/2/3/4/5。

* DDL 权威脚本：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/sandbox_schema.sql` + `i2s1_verify.py`（26 项校验，报告 `i2s1-report-r3.json` write-once）。

* 重跑脚本：`audits/20260919-i3-1-e2e/run_i3_1_approved_set.py`（ReviewedDecision 登记 → build/check/publish 链路，缺口过滤按 disposition，L148-152 —— **本轮须改按 lifecycle 过滤**）。

* 冻结模式：`freeze_r32.py`（archive-first → 构造冻结 JSON → validate → 台账回填）；`sign_and_freeze_r33.py`（先归档 before-rNN）。

## 实现步骤

### 1. 裁定记录（先落）

`audits/20260919-i3-1-e2e/decision-gap-approval-entry-20260920.{json,md}`，仿 `decision-old-doc-kind-review-authority-20260919.json` 模式：`decided_by=U`、`decided_at=2026-09-20`、decision\_text 记 ①人工认可入口 ②格式覆盖先不动（v1 有效覆盖=PDF，DOCX/MD 不声称，§12.1 挂起）、binding 相关审计产物。

### 2. 契约（contract.py + gaps.py）

* `contract.py` 新增 `GapApprovalDecision(StrEnum)`：仅 `ACKNOWLEDGE = "acknowledge"`（词表唯一来源，构造即拒绝非法值，仿 `ReviewDecision`）。

* `gaps.py` 新增 frozen dataclass `GapApproval`（**放 gaps.py 而非 contract.py**，避免与 `parse_gap_key` 成环导入）：
  `approval_id / source_id(SHA-256) / gap_key / reviewer / reviewed_at / decision / rationale / operator / supersedes=None / evidence_ref=None / scope_ref=None`
  `__post_init__` fail-closed：approval\_id/reviewer/operator 非空、source\_id 为 SHA-256、decision 是枚举实例、rationale 非空、`parse_gap_key(gap_key) is not None`。

### 3. grading 扩展（gaps.py）

* 新增 `GapLifecycle.HUMAN_ACKNOWLEDGED = "human_acknowledged"`。

* 新增 `apply_gap_approvals(records, approvals)`：按 `record.key == approval.gap_key` 匹配 → `replace(record, lifecycle=HUMAN_ACKNOWLEDGED, basis=f"human_acknowledgement:{approval_id}")`；approval\_id 重复 → ValueError。

* `blocking_gaps()` 零改动（`is BLOCKING` 天然排除新生命周期）。

* `acknowledged_gaps()` 改为 `lifecycle in (ACKNOWLEDGED, HUMAN_ACKNOWLEDGED)`（人工认可键进 PUBLISHED 检查点留痕）。

* `gap_summary()`：`acknowledged` 保持默认放行计数，新增 `human_acknowledged` 计数；`blocking` 语义不变。

* `recovery_paths()`：HUMAN\_ACKNOWLEDGED 进通用分支（有 entry、无 command），entry 增 `approval_ref`。

* **`GAP_POLICY_REV`** **不升版**（默认分级表与判定顺序未变，每笔认可自带 approval\_id 证据链）。

### 4. 引擎接线（engine.py）

* `gap_records_of(build)` → `gap_records_of(store, build)`（L1119）：先 `evaluate_against_scope`，后 apply 认可（out\_of\_scope 记录不被认可改写）。

* 新增 `resolve_gap_approval_chain(approvals)`（gaps.py，仿 admission `resolve_review_chain`：approval\_id 唯一、断链/多根/环 → 冲突 fail-closed）+ `_effective_gap_approvals(store, source_id)`（engine.py，经 `store.list_gap_approvals`）。

* 认可键不在 build 台账或对应记录非 blocking → 抛 EngineError（认可不存在的 gap key 拒绝，fail-closed）。

* `_verify_publication_ready` L1173 改 `blocking_gaps(gap_records_of(store, build))`；错误文案保留 `gap_regions` 前缀（探针兼容）。

* `_acknowledged_keys_of` 签名加 store，调用点同步传。

### 5. 存储层 + DDL

* `repository.py`：Store 接口（L58 附近）+ MemoryStore 新增 `put_gap_approval / get_gap_approval / list_gap_approvals(source_id)`（内存 dict + 同内容幂等/异内容拒绝）。

* `repository_pg.py`：三方法仿 L389-448；新表：

  ```sql
  corpus.corpus_gap_approvals (
    approval_id text PRIMARY KEY,
    source_id char(64) NOT NULL,
    gap_key text NOT NULL,
    reviewer text NOT NULL,
    reviewed_at timestamptz NOT NULL,
    decision text NOT NULL CHECK (decision IN ('acknowledge')),
    rationale text NOT NULL,
    supersedes text REFERENCES corpus.corpus_gap_approvals(approval_id),
    evidence_ref text, scope_ref text
  );
  CREATE INDEX idx_gap_approvals_source_key ON corpus.corpus_gap_approvals (source_id, gap_key);
  ```

* `i2/sandbox_schema.sql` 补第 10 表；`i2s1_verify.py` 的 EXPECTED\_COLUMNS/FKS/PKS/index\_names 增表与索引，REPORT 常量改 **r4**（r3 write-once 不容覆写）。重验：`i2s1_teardown.py` → `i2s1_apply.py` → `i2s1_verify.py`（CORPUS\_I2\_DSN）。

### 6. CLI（cli.py）

* 新增 `gap-approve` 子命令：必填 `--source --gap --reviewer --rationale --operator`；可选 `--approval-id --supersedes --evidence-ref`。缺参→2，ContractError→2，StoreError 拒绝→3，链冲突→4，成功 0。注册进 `_HANDLERS`。

* `check`/`status`：`_gap_view` 增 `gap_approvals`；gaps 逐条已带 `lifecycle=human_acknowledged` + `basis`；`gap_summary` 带 human\_acknowledged；recovery 带 approval\_ref。

* `_precheck_entry`（plan 预检）无 store → 无认可，保持"只更严"。

### 7. 测试与反例

新文件 `tests/test_corpus_gap_approvals.py`（≥10 条）：

1. 认可转放行可发布（check 0 + publish 0）
2. 未认可仍拒绝（exit 4）
3. 同 approval\_id 异内容 → StoreError
4. 断链 supersedes → 冲突、门仍拒绝
5. 环 → 冲突 fail-closed
6. 认可不存在的 gap key → EngineError
7. 新认可取代旧认可（链尾生效）
8. human\_acknowledged 仍进 gap\_summary/coverage（`gap_regions_present`）与 PUBLISHED checkpoint
9. 无认可时门与 summary 形状不变（向后兼容）
10. 缺 operator/reviewer/rationale → ContractError；非法 gap\_key → 构造拒绝
11. 与 out\_of\_scope 共存（blocking 认可后发布，out\_of\_scope 生命周期不变）

跑法：`uv run pytest tests/test_corpus_gap_approvals.py -q`；PG 用例 `CORPUS_I2_DSN=... uv run pytest tests/test_corpus_gap_approvals.py -q -k Pg`。

### 8. 守卫重验

`guards/i3-e2e.json` 字节不变（批准集 6 份、零模型、forbidden\_roots 不变）；复用 `i3_e2e_guard_selfcheck.py` 报告（config\_sha256 匹配，24/24）。

### 9. 照批准集重跑

新脚本 `audits/20260919-i3-1-e2e/run_i3_1_approved_set_gap_approved.py`（改造 run\_i3\_1\_approved\_set.py）：

* 对 13 处 blocking 缺口逐笔登记 `GapApproval`（reviewer=xyl、operator 必填、rationale=人工可视核验记录、evidence\_ref=页/元素坐标）。

* **缺口过滤改按 lifecycle（blocking 判发布），不得按 disposition**。

* 预期：6/6 可发布、per\_class\_min\_2\_satisfied=true；产物 `i3-1-e2e-approved-set-gap-approved.{json,md}`。

* 检索/取证/coverage/审计沿用原脚本口径。

### 10. 冻结 r34 + 台账回填

* 新脚本 `audits/20260919-i3-1-e2e/freeze_r34.py`（仿 freeze\_r32.py：archive-first 归档 before-r34 → 写 i0c-r34.json + freeze-manifest 索引 → 补 validate\_i0c\_freeze.py r34 块 → 台账回填 → 跑验证器 exit 0）。

* r34 绑定：5 个 preparation 模块 + cli.py + 新测试 + sandbox\_schema.sql + i2s1\_verify.py + 裁定记录 + 重跑产物 + freeze 脚本 + 验证器 + 两份台账。

* **注意**：r32 验证器块曾断言"不得绑定 plugins/tests"（r32 特有约束），r34 块须显式放宽并声明为合法绑定范围，否则冻结必失败。

* 台账回填：`docs/plan/corpus-ingestion-rebuild-tasks.md` + `claims-market-closed-loop-plan.md`（r34 优先状态：人工认可入口已落、照批准集 6/6 可发布、per\_class\_min\_2 满足、格式覆盖仍仅 PDF）。

## 验证

```bash
uv run pytest tests/test_corpus_gap_approvals.py -q                      # 内存全部用例
uv run ruff check plugins/corpus tests/test_corpus_gap_approvals.py      # lint
uv run pyright                                                        # 类型
uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/run_i3_1_approved_set_gap_approved.py   # 重跑（守卫 env）
uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/freeze_r34.py   # 冻结，内含 validate exit 0
```

## 风险与边界

1. **PG 迁移 vs 测试隔离**：第 10 表只进 sandbox\_schema.sql；重跑/PG 测试前必须 teardown+apply；报告用 r4，不得覆写 r3。
2. **r34 验证器块**：须显式放宽"不得绑定 plugins/tests"的 r32 特有约束，否则冻结失败（本轮最大机制坑）。
3. **探针兼容**：发布门错误文案保留 `gap_regions` 前缀；重跑脚本过滤改按 lifecycle。
4. **coverage 语义**：human\_acknowledged 后 quality\_report 台账原样保留（`gap_regions_present`/`scoped` 不变），只改生命周期，不得"清空缺口"式放行。
5. **i1 链**：本轮不动 freeze\_utils/合并顺序逻辑，i1-r1..r4 不受影响。

