# R2 原子义务开发轮报告

日期：2026-09-14  
状态：失败后停止；方向获得支持，但 R2 未验收通过

## 执行边界

- 冻结预算：`r2-atomic-development-budget-v4.json`
- 模型：`glm-5.3-flash`
- 范围：4 个 development 类目；holdout 0；关系调用 0；不入库
- item 调用：计划上限 35，实际 35，无重试
- 协议：系统生成原子槽，模型逐槽输出 item 或 `no_supported_item`，每槽必须有 coverage

## 结果

| 口径 | 结果 |
|---|---:|
| 选定 item recall | 24/24 |
| critical item recall | 23/23 |
| semantic accuracy | 24/24 |
| attribution accuracy | 23/24 |
| critical all-fields | 1/23 |
| 微型穷举 item recall | 31/35（88.6%） |
| 微型穷举 item precision | 31/32（96.9%） |
| 微型关系正例 recall | 0/17（本轮延期） |
| 可判负关系规避 | 8/8 |

四类材料的 item 相关指标相对同评分器 capability 基线逐类没有退化。正式跨类目门禁仍失败：关系
延期使 relation recall 下降，全部候选包按约定为 partial；不能以 item 提升替代完整 R2 验收。

## 失败证据

- 公司微型范围漏 3 项：评级、消费复苏风险、行业竞争风险。
- 铜箔总结只抽首个子命题，与现有长摘要金标的边界不一致。
- 系统发现 7 个槽仍被模型填入多个 item，证明这些复句仍需拆分。
- 铜箔 28 个 item 批次中 26 个 coverage 不完整，累计 39 个槽缺 coverage；所有调用均正常
  `finish_reason=stop`，不是输出 token 截断。
- `unknown_fields` 仍是主要全字段失败源，不能靠提高召回解决。

## 停止与后续

冻结预算已用尽，不进行第二轮调用，不访问 holdout，不启动 R3。v11 仅完成离线修正：每槽最多一个
item、每槽只返回一条 item/no-supported 终态记录、信号优先级归一、补充复句边界、quoted source
系统接管、关系候选逐对 present/absent。
下一轮若获准，必须重新冻结更小批次预算，并把 item-phase 与完整 R2 门禁分开报告。

## 可复核产物

- 开发报告：`material-semantics-runs/report-41375baa853ecfec08fcb8b0ffa10ca2da4960387c73cda07607308448c0ea94.json`
- 微型报告：`material-semantics-runs/micro-score-bcde356c19bc4df28926ff16939782d4796e67019100467cdc8cee6523b302f9.json`
- 开发报告 SHA-256：`0f894fe9942fc7f0bd4d5d4f41f50401433e50fe3d380d8e09279d8770fa959f`
- 微型报告 SHA-256：`6df7a84abe6a3f6618b5f0ea77b978ce42193c120960bfabeda72d6b83928c03`
