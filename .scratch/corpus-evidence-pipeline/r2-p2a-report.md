# R2 P2-A：独立 item 验收器与输出变异测试

日期：2026-09-14。归属：R2 / P2 的第一段，不新增跨层优先级。

## 当前结论

**已完成 P2-A 离线 item 验收器及合成输出反例；P2 整体仍为 partial。**
本轮未开始 R2 私有生产执行链、fake 关系协议、调用账本及响应保存故障测试；不能进入 P3/P4 或
冻结真实模型预算。P0-PG 仍未验证，v13 历史失败和停止状态不变。

真实模型、评审模型、真实市场请求、入库、生产数据库连接、holdout 原文读取均为 0。没有访问真实
开发金标进行新语义裁决，没有修改旧 scorer/policy/budget/gold 或公共生产代码。

## 交付

- [r2_evaluation_v1.py](r2_evaluation_v1.py)：新路径的纯输入/输出 EvaluationReport；不覆盖旧评分器。
- [test_r2_evaluation_v1.py](test_r2_evaluation_v1.py)：73 项新合成测试，包含正确正控和错误负控。
- [p2a-validation-final.xml](p2a-validation-final.xml)：最终逐测试记录；156 passed = 新73 + P1既有65 + P0工具既有18。
- [r2-p2a-manifest.json](r2-p2a-manifest.json)：本轮代码、测试、最终结果、快照与 P0/P1 契约绑定。

冻结清单的外部 SHA-256：

```text
72d5eb692bf44ad7f5dd61fa82e1db3e8e8cce72ee2fa461014c991e9e990cbf
```

策略内容 SHA-256：`be7ee183d71094b78b646b16b6e661722649725979a4bb52d177cd3c6b9a3062`。
这里的策略是 P1 前瞻契约的 item 评分实现，不是新预算。早期迭代的 `p2a-validation-results.xml`
不是最终冻结结果，不应把其72项与最终156项相加。

## 实现口径

Interface 为 `evaluate(source, plan, result, gold, reviews, pins) -> EvaluationReport`。
它属于离线评测，不是生产模块或正式材料 CLI。使用 P1 冻结的纯规划规格校验来源/计划；生产层
不得反向 import 本文件或 P1 scratch 规格。后续私有执行链通过明确的离线投影对接，不能复制一条
“只为考试”的提取链。

1. **外部固定身份**：source/plan/result/gold/reviews/contract/policy 分别绑定。Pins 由受信任的
   运行器提供，不从模型输出或裁决文件自取。模型输出换了 hash，不意味着旧内容裁决仍有效。
2. **校验全部记录**：重复/未知/漏终态、缺响应、截断标记、无项却携带 item、重复 item ID 不能过门。
   预测分母包含全部 item，非法记录不能被过滤后抬高 precision；目标召回包含遗漏目标。
3. **内容与标签分离**：忠实度、原子性、条件保留使用明确裁决；十个字段轴独立评分，包括
   semantic_type、statement_role、话语角色、归属、视角、极性、行为、时间、数值和单位。
   不靠引文相似度自动认证正文，不把正确标签当正文忠实。
4. **未知与数值不补造**：unknown 与确定值矛盾、把语义判断标为 source_observed、无来源数值、
   未批准的 transform 均拒绝。数值采用保守的原文字面 token/数值—单位组合校验，不是财务换算器；
   尚未支持的转换不自动通过。不能因 `1` 是 `100` 的子串就认为该值有证据。
5. **阈值方向明确**：召回/precision 用 min；关键错误用 max=0；空分母为 not_applicable，不能使
   必需门通过。错误标签同时产生该标签 false positive 和原标签 false negative。
6. **人工批准不能伪造**：agent_proposal 即使自标 approved 也不接受；synthetic_fixture 只能用于
   synthetic 模式。development 接受人工裁决时，审核者必须在外部提供的 allowlist 中，且文件 hash
   已固定。测试使用的 unit-test-human 仅是合成数据测试身份，不是本轮真实人工批准。

输出的 `local_item_gates_passed` 仅描述该规范化评测输入上的 G0—G3；G4—G7 明确 not_evaluated，
`budget_authorized` 恒为 false，不能被当作模型预算或运行时业务放行。

## 反例实际结果

| 反例/正控 | 实测结果 |
|---|---|
| 正确的条件预测、行为意图和寒暄排除 | item recall=2/2、precision=2/2、忠实度=2/2、关键错误0；局部 item 门通过，预算仍不授权 |
| 同一个短引文在 packet 出现两次，固定坐标合法 | 可通过，不因全包字符串重复误丢项 |
| 编造正文、翻转否定、删条件、扩对象、删约束；结果重新合法哈希 | 旧裁决失效，出现待裁决项，不放行 |
| 显式裁决为不支持、多命题、条件未保留、未知或关键错误 | 内容门阻塞，不以正确字段标签抵消 |
| 关键错误计数0、1、35 | max=0 仅允许0；原“上限被按下限比较”漏洞被负控覆盖 |
| partial/非法枚举、重复/未知/缺终态、截断、缺响应、审计不完整 | schema 或协议门拒绝；系统终态数不是业务完整性 |
| 全拒绝或空输出 | 正目标召回失败；空 precision 分母不是通过 |
| unknown 冲突、语义来源升级、数值/单位缺支持、未批准转换 | 字段或证据门拒绝 |
| 语义标签错、statement_role 从 condition 改 claim | 逐轴失败；不遗漏 statement_role 评分 |
| 修改评分上限并重新计算配置 hash | 与本版本固定策略不符，G0 拒绝 |
| 代理建议、未批准审核者、过期裁决、原子金标分母未批准 | 不放行；不会自动生成新人工批准 |
| 禁止 open/read_text/read_bytes/socket.connect 后执行 | 正控仍通过，评分无隐式 I/O |
| schema 错误含私有正文标记 | 错误报告只保留错误码，不回显私有 payload |

以上都是合成正误预期，**不是 v12/v13 或四类真实研报的新评分**。对任意新转述，纯规则不能普遍
证明语义忠实；未取得有效裁决就保持阻塞，而不是让评分器自己编造答案。

## 对旧流程的保护

- P0/P1 外部固定清单与绑定文件复核通过；公共模块未修改，没有启用任何文件/方法例外。
- 本轮最终组合测试156项通过、0失败、0跳过，1.45秒；没有重跑此前全部605项工程测试。
- 新验收器与测试 Ruff 通过；验收器目标 Pyright：0 errors / 0 warnings。
- 两阶段 import smoke：336/336、385/385；check_symbols：435文件、0缺失。
- 新进程 R2 禁用快照与 P0 原快照逐字一致：
  `p0-baselines/baseline-4e2c45ce216a9421/snapshot-p2a-r2-disabled.json`，SHA 为
  `847f3381a5c2f86a86b0efcde6ae79efceba7e9662e964962e69071a06b0133b`。

快照仍用固定合成资料、临时 SQLite、内存证据存储与 MockTransport；example.test 日志不是实际
网络访问。真实模型 preflight 因零预算未运行；未跑全库 Pyright/CLI 业务 E2E 或 PG 集成。
这些检查不能替代 P3 真实开发逐类非回归，也不能把尚未验证的36项 PG 测试算通过。

## P2 剩余工作与进入限制

当前 Result 是**规范化评测输入，不是模型 wire format**。其中 response_received/audit_complete
目前由输入声明并接受否定检查，尚未独立从 raw response、attempt ledger 验证。未来运行器必须
从可信审计产物导出，不能让模型填写。这是 P2 尚未完成的重要部分，不是当前已经闭合的保证。

下一段依次执行：

1. 前瞻登记 R2 私有新文件与专属测试的精确变更清单；保留 P0 原 manifest，不用重新冻结掩盖漂移。
2. 实现新的私有 prepare/execute/validate，调用既有 EvidenceRun 身份核验；旧入口和公共 parser 不动。
   规范化输出跨同一 Interface 对接本验收器，fake/replay 不补造缺失字段。
3. 验证 fake 关系协议、非法端点和依赖隔离；不把八种 R1 关系需求缩成已测三种。
4. 实现 durable reservation、崩溃/恢复/并发负控、公开响应完整留存及落盘失败停止，再从审计证据
   验证输入中的 response_received/audit_complete，而不相信布尔自报。

以上未完成前，不把 P2 标完成、不跳到 P3，不创建新模型预算。P3 仍须既有35项目标的原子粒度差异
裁决、四类/六微范围回放与非回归、长开发容量/成本评估；本轮不要求新增纪要或生产密钥。

## 复核

先校验本报告外部固定 manifest SHA 及其 files，再在 WSL 仓库根运行：

```bash
uv run pytest .scratch/corpus-evidence-pipeline/test_p0_baseline.py \
  .scratch/corpus-evidence-pipeline/test_p1_planner_spec.py \
  .scratch/corpus-evidence-pipeline/test_r2_evaluation_v1.py -q
uv run ruff check .scratch/corpus-evidence-pipeline/r2_evaluation_v1.py \
  .scratch/corpus-evidence-pipeline/test_r2_evaluation_v1.py
uv run pyright .scratch/corpus-evidence-pipeline/r2_evaluation_v1.py
```

重跑不覆盖冻结的最终 XML；如需另存结果，使用新的文件名。
codebase-design 的 Interface/Seam 方法在本轮用于隔离评测与运行时：gold 和裁决留在离线侧，
没有为了评分便利修改公共来源模块或把评测逻辑接入生产。
