# R2 P2-B：私有离线执行、响应审计与 fake 关系协议

日期：2026-09-14。归属：原计划 P2 第二段；Web 暂缓，正式 CLI 接线尚未实施。

## 结论

私有执行链和零模型协议测试已实现并通过；**P2 仍 partial，P3 暂停**。本轮回归入口首次漏装
PG/网络阻断，确实触发了既有 PG 测试。入口已修复，离线回归已重新通过，但数据库影响尚未核查。
详见 [执行偏差与影响报告](r2-p2b-guard-incident.md)。不能把源码未改、测试全绿表述为数据库零影响。

真实模型/评审模型预算仍为 0，没有真实模型调用，也没有调用真实市场接口。未执行用户提供
文档的重新入库；但首次 PG 测试执行了合成数据写入、测试 schema 创建/删除和现有语料读取，
因此不能宣称本轮所有入库/数据库/真实语料访问均为 0。旧 v13 失败及关闭状态不变，R2 未验收。

## 已交付的隔离边界

在动工前冻结 [additions-only 范围](r2-p2b-change-scope.json)，外部 SHA：
`296db21dfd5ff9e890b5793767353060161e3a757453bf6718ad364c3583fc12`。
原 2336 个受保护文件零修改，仅新增三份 R2 私有代码：

| 文件 | 职责 |
|---|---|
| `plugins/corpus/_r2_plan.py` | 原样实现 P1 冻结 planner 的算法/身份规则；有限结构候选，歧义保持 unresolved |
| `plugins/corpus/_r2_audit.py` | 显式路径的临时 SQLite journal；发送前事务预留、完整公开正文保存、未知结果占额并停止 |
| `plugins/corpus/_r2_runtime.py` | EvidenceRun → prepare → fake/replay execute → 从 raw 重建并 validate；独立 item/关系批次 |

生产层不 import scratch/gold/evaluator；[离线投影](p2b_projection.py) 先核验原始响应与外部
hash，再逐字段转换到已冻结的 P2-A evaluator，比较新旧 planner 序列化完全一致，不补造字段。
codebase-design 技能用于保持“准备、执行、验证”接口边界，以及运行时校验/开发评分的单向依赖。
默认 CLI、工具注册、service、公共 parser、财务公式、原 scorer/金标/预算均未修改。

## 协议与实际能力

- `prepare` 校验 EvidenceRun 身份及外部完整 hash；源文字只作为不可信材料。义务仍是待核验
  结构候选，不把切句结果称作已验证原子命题。上限继承 P1；请求每批最多 8 项。
- `execute` 默认零调用；只有显式 journal + fake/replay adapter 才执行离线响应。模型 wire
  不能提供 `response_received`、`audit_complete`，也不能伪造系统 failed/deferred 终态。
- JSONL 按记录验收：非法、未知、重复或缺终态都记错，同批合法项保留；所有原定义务仍留在
  分母中。预算耗尽为 deferred，不缩分母；数值来源/单位保守校验，未实现的转换拒绝。
- raw/request/attempt/result 分别绑定；validate 从原始公开正文重新解释，重新 hash 的伪造
  Item 不能覆盖原响应。正文忠实度仍需离线裁决，ValidationReport 始终 semantic not_evaluated。
- journal 在 SQLite `BEGIN IMMEDIATE` 内预留，保存提交后才调用 adapter；恢复已 received
  的 attempt 不重发，reserved/unknown/failed 停止新调用。没有供应商幂等支持，不承诺 exactly-once。
- 关系输入由系统显式给定已提取端点、有向 pair 和八种类型之一；同时提供固定端点正文及来源。
  模型只填 present/absent/unresolved 和 provenance。此处验证关系协议，不自动判定真实关系，
  也不是 G4 关系语义验收器或关系候选生成质量验收。

`OfflineGrant.plan_id` 绑定完整 `Prepared.prepared_id`（含关系范围），不是仅绑定内部 planner
的 plan_id。journal 必须由可信运行器固定路径和 grant，snapshot/result hash 必须外部保存。
文件权限 0600；新建 journal 不等于恢复旧轮次。临时测试目录/账本不是第二套 claims 库。

当前没有真实 provider、全局模型轮次注册表、token/时间/金额上限或正式 CLI 接线。fake/replay
是可信注入接口，不是对任意 Python adapter 的 OS 沙箱；本阶段不能授权真实调用。未来接入真实
模型前仍需单独实现并验证预算、运行器保存和权限边界，不能直接把 mode 改为 real 后调用。

## 验证结果

| 检查 | 最终结果与证据 |
|---|---|
| 新私有链/审计/协议测试 | 75 passed；含 3 项入口阻断回归 |
| P1 + P2-A + 本轮组合 | 213 passed = 65 + 73 + 75；`p2b-validation-guarded-final.xml` |
| 旧 corpus/market 等 | 495 passed、36 PG skipped、1 真实源用例 deselected；`p2b-core-guarded.json` |
| 旧 workflow/registry/profile | 110 passed；`p2b-platform-guarded.json` |
| 禁用新旧 R2 的重复子集 | 169 passed、1 PG skipped；`p2b-isolation-guarded.json`；不能与 605 累加 |
| 旧行为快照 | 与 P0 逐字一致；`p2b-old-path-snapshot.json` |
| 保护范围 | 原2336文件与54资产不变；P1/P2-A冻结清单不变，仅增加登记的3文件 |
| 静态检查 | 六份新增实现/测试 Ruff 通过；三份私有模块 Pyright 0 errors / 0 warnings |
| 分层与符号 | import smoke 339/339、388/388；check_symbols 438 文件、0缺失 |

快照 SHA：`847f3381a5c2f86a86b0efcde6ae79efceba7e9662e964962e69071a06b0133b`。
没有运行真实模型 preflight（预算为0）、全库 Pyright、正式 CLI 业务 E2E 或获准的隔离 PG 验收。

故障反例覆盖：发送前预留后中断、收到响应但保存前中断、保存后中断；真实子进程退出后重开
SQLite；两连接竞争同一次预留；响应保存及失败记录同时写失败；超容量正文完整保留并停止；
9义务/1次预算保留第9个 deferred；缺失/重复/截断/非法字段时保留合法兄弟记录；外部 hash、
raw/request/status/result 篡改拒绝。八关系类型各有 present/absent/unresolved 合成协议检查。
合成端到端正控确实经过 execute → raw 校验 → 投影 → 冻结 evaluator，item 2/2，预算仍不授权。

## 复验方式与原基线兼容

冻结清单：[r2-p2b-manifest.json](r2-p2b-manifest.json)。外部 SHA-256：
`85d587047b680b5c76ca985f63945ec243d69e7d16e8ddf35a5596144b72ab3f`。
清单分别绑定有效结果、作废结果及偏差报告，不因冻结而给作废结果恢复验收资格。

原 P0 verifier 不支持新增文件，仍保持原样；不能直接运行它后把“发现3个新增”解释成旧文件漂移。
新 guard 对旧文件执行同一 hash/inventory/环境/资产检查，仅允许外部 scope 登记的三项新增：

```bash
uv run python .scratch/corpus-evidence-pipeline/p2b_guard.py verify
uv run pytest .scratch/corpus-evidence-pipeline/test_r2_runtime_v1.py \
  .scratch/corpus-evidence-pipeline/test_r2_evaluation_v1.py \
  .scratch/corpus-evidence-pipeline/test_p1_planner_spec.py -q
uv run python .scratch/corpus-evidence-pipeline/p2b_guard.py suite \
  --suite core --out /absolute/new/path/core.json
```

suite 支持 core/platform/isolation，snapshot 支持 `--out`；输出必须是新路径，不覆盖历史证据。
运行之前还应核对本轮冻结清单及其独立 SHA，不以报告里的静态通过数代替现时校验。

## 出口与下一步

技术实现可供后续离线评审，但因执行偏差，本轮不放行 P2、不进入 P3，也不追加模型预算。
先由用户确认/授权数据库只读影响核查；缺少前置快照的影响保持未确认，不能自行修复或删库。
解除此门后，原下一阶段仍是 P3：四类/六微范围旧响应可回放性清单、原子分母差异与人工裁决、
长开发范围容量评估、逐类非回归及故障注入。不得拿 fake 填缺字段冒充旧响应实测通过。
P0-PG 正式隔离门仍未验证；R3/正式 CLI、真实模型 item、关系实测、留出继续各自独立验收。
