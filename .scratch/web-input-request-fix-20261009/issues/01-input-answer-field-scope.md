# 01 补数回答的字段范围与无快照续接

Type: bug
Status: ready-for-human（待独立复核 + 用户签认；实施方不自宣完成）
依据：[spec.md](../spec.md)

## 复现（修改前）

研究还没有账户/计划时，worker 意图落库出的请求含 8 个字段（`evaluate_purpose` 结果）。
弹窗内联创建主账户后提交"规划资金 + 承受风险 10% + 期望盈利 10%"，服务端返回

```
400 unknown_field_rejected / 回答包含未请求的字段
fields = plan.risk_budget_value, plan.risk_budget_unit, plan.target_profit_value, plan.target_profit_unit
```

整条回答事务回滚（账户创建是另一次调用，已提交）——用户看到的是半写入状态 + 原始 JSON。

## 根因

1. `server/input_requests.py::answer_request` 多设了一道"submitted ⊆ requested"限制
   （错误文案"请只回答本次待补字段"）。而 PRD §4.2/AC-30 要求弹窗把三项一次收集保存，
   后两项按用途裁决并不是请求字段 → 必然 400。契约 §8 并无此限制。
2. `_spec_json` 只存 `{"id": ...}`、`_spec_from_research_link` 不带版本 → 无快照续接的
   `known_versions` 为空、对象引用为 `null`；用户按引导补齐对象后，
   `persist_declared` 报"保存资料需要明确的目标对象"、`_with_expected_versions` 报
   "回答缺少资料版本"，请求永远走不完。
3. `web/src/api/client.ts` 只解包 FastAPI 的 `detail`，业务信封 `{"error": {...}}` 落成整段
   JSON 文本（截图里的那坨），字段级原因与 `code` 都丢了（`AnalysisEvidence.vue` 依赖
   `detail.code === "snapshot_absent"` 的既有分支也因同一原因失效）。
4. `ChatView.maybeOpenInputRequest` 对任何 pending 请求都弹专用弹窗，而弹窗字段集固定，
   不匹配时用户只会看到"仍有待澄清项"。

## 修复落点

| 文件 | 改动 |
|---|---|
| `server/input_requests.py` | 回答字段范围改为"业务契约内"（契约外仍 `unknown_field_rejected`）；新增 `_adopt_research_bindings`（按研究当前绑定补全 `null` 引用，锁下读版本）+ `_live_ref`；`_with_expected_versions(adopted=…)`；无快照续接 `_spec_json(keep_versions=True)` 记录当时版本；顺手修该文件一处存量 pyright 报错（`_aware` 返回 Optional 的比较） |
| `web/src/utils/apiError.ts`（新增） | 解包业务信封：`detail` 取内层 `error`（`code`/`fields` 可用），展示文本取 `message`；`messageFromDetail` 从 `client.ts` 移入 |
| `web/src/api/client.ts` | 改用上述解包（行为不变：`detail` 优先、空体 `null`、非 JSON 原文） |
| `web/src/utils/inputRequest.ts`（新增） | `dialogCoversRequest`：弹窗只对它能采集并申报的字段集自动打开 |
| `web/src/views/ChatView.vue` | 自动弹窗加上该判定 |
| `web/src/components/business/BusinessInputRequestDialog.vue` | 内联创建主账户时把**同一批账户事实**随回答申报（否则请求里那些账户字段永远补不上）；pending 时列出服务端返回的 `remaining_fields` |

## 验证（本机实跑）

| 项 | 命令 | 结果 |
|---|---|---|
| 缺陷路径 harness（SQLite，服务层） | `uv run --no-sync python .scratch/web-input-request-fix-20261009/evidence/input-answer-harness.py` | **10/10 通过**（A 报告路径不再 400、可后补项入 collected、剩余字段如实；A5 负例：`plan_price` 仍 `unknown_field_rejected`；B 冻结引用为 null 也能续接；C 续接记录版本后可完成） |
| 定向用例 4 项（SQLite 等价副本） | `uv run --no-sync pytest tests/tmp_field_scope_sqlite_check.py -q` | **4 passed**（副本已删除，正式版本见 `tests/pg/`） |
| 前端单测 | `node --experimental-strip-types --test "src/**/*.test.ts"` | **84 passed / 0 failed**（新增 `apiError` 4 项 + `inputRequest` 4 项） |
| 前端类型检查 | `node ./node_modules/vue-tsc/bin/vue-tsc.js --noEmit` | 无输出（全绿） |
| 前端构建 | `node ./node_modules/vite/bin/vite.js build` | built in 4.70s（仅既有大 chunk 警告） |
| Ruff（本批文件） | `uv run --no-sync ruff check server/input_requests.py tests/pg/test_input_request_field_scope.py` | All checks passed |
| Pyright（本批文件） | `uv run --no-sync pyright server/input_requests.py tests/pg/test_input_request_field_scope.py` | **0 errors** |
| import smoke / symbol closure | `uv run --no-sync python tools/import_smoke.py --stage 1` / `tools/check_symbols.py` | 388/388、486 文件 0 缺失 |
| `git diff --check` | — | 通过 |

日志：[input-answer-harness.log](../evidence/input-answer-harness.log)、
[pg-cases-on-sqlite.log](../evidence/pg-cases-on-sqlite.log)。

## 缺口（不放行，登记在案）

1. **`tests/pg` 定向 4 项未在本机执行**：本机没有 PostgreSQL（`PG_INTEGRATION=1` +
   登记测试库才能跑，见 `tests/pg/conftest.py`），`tests/pg` 本机全部 skip。已把同一批用例
   在隔离 SQLite 副本上跑通（4 passed）以验证用例与逻辑，但**正式 PG 运行尚未发生**。
2. **前端无浏览器/端到端验收**：弹窗自动弹出的判定、四字段流程、错误信封展示只做了单测 +
   类型检查 + 构建，未跑 Playwright/真实后端联调（沿用上游 issue 05"未做"的口径）。
3. **全量 `pytest -q` 有 12~19 项失败**，全部落在并行会话正在改的 corpus 域
   （`plugins/corpus/structured/cli.py`、`ledger.py`、`plugins/corpus/material_semantics.py`
   在 `git status` 里为他人改动）与需要外部数据的 market/F19 用例；本批文件无交集。
   **未做 pristine 基线**（避免与并行会话的 git 操作互相干扰），因此不宣称这些失败"改动前也有"。
4. **产品口径待裁决**：无主计划时 `plan.symbol/market/direction` 无人可采集（PRD §4.1 规定
   计划从"会话计划"入口创建）。当前行为是服务端如实报错、请求留在补数中心；是否改为弹窗内联
   创建计划，需用户裁决。
5. **口径变更需具名签认**：回答字段范围由"本次请求列举"放宽为"业务契约内"。

## Comments

2026-10-09：按"修复bug"指令实施；三条判定（字段范围、续接引用/版本、错误信封）+ 弹窗路由，
证据与缺口如上。**未部署、未迁移、未改生产数据**。
