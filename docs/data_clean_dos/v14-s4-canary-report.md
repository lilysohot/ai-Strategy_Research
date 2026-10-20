# S4 RC1 只读预切换验证报告

执行时间：2026-10-20 11:17–11:32（Asia/Shanghai）

结论：`CANARY_PASSED`

## 范围

本次在独立工作树 `/home/administrator/FrontierAgent-rc1` 启动 8001 实例，代码固定为
`corpus-v14-s4-rc1`（`58260fbc60ad65129bbb98a47c07defc0850622f`）。RC1 manifest 的
SHA-256 为 `5951a6e9328d4ce889f3cbf351c0f3159b5c4f5bce23f71c2332e0a5d8eba823`，
与冻结记录一致。

验证仅执行 `corpus_search`、`corpus_fetch`、健康检查和显式只读数据库查询。没有调用回答模型、
Judge、网页搜索或行情工具，没有发布 build，没有更改 `corpus_publications`，也没有切换或重启
生产 8000。

## 结果

- 8001 的 `/healthz`、`/readyz` 启动检查与结束检查均为 200。
- 8 个冻结活动 build 全部存在、仍为 active，unit/chunk 数逐项等于冻结基线。
- 数据库为 `postgres`，核验事务为 read-only；运行中 job 为 0。
- 9 张 corpus 表的行数在探针前、探针后和观察结束时完全一致：8 个 source、14 个 build、
  7,128 个 unit、1,214 个 chunk、8 个 publication、42 个 job。
- 活动发布的 8 组 `(source_id, active_build_id)` 与冻结基线逐项一致。此次报告另按规范化 JSON
  计算的集合指纹为 `8c0c8c07e7ff8d9273dc65fc01e3726e420eb9b34fb26e01f717dd91ea71e26e`；
  冻结文件中原口径指纹 `5475ac32…` 原样保留，两者算法不同，不作为漂移信号。
- 15 分钟内按 30 秒间隔取得 31 个样本，31/31 通过；每个样本均满足健康、就绪、发布集合、
  build 计数、表计数和 running job 条件。
- 6 个既有开发金标问题全部把目标来源排在第 1 位，并成功取回权威正文：company 2 题、
  industry 2 题、macro 2 题。`company-003` 因完整表格载荷走分页信封，其余 5 题走单块
  `text/units` 返回；两种都是 `corpus_fetch` 的正式契约。
- 模型调用 0，Judge 调用 0；`openai`、`anthropic` 未加载。

| 探针 | 领域 | 目标来源排名 | 取回形态 | 定位 | 正文字符 |
|---|---|---:|---|---|---:|
| company-003 | company | 1 | page envelope | `table:0024` | 365 |
| company-005 | company | 1 | direct | `table:0005` | 288 |
| industry-001 | industry | 1 | direct | `table:0022` | 346 |
| industry-005 | industry | 1 | direct | `body:0008` | 547 |
| macro-001 | macro | 1 | direct | `body:0001` | 1,223 |
| macro-008 | macro | 1 | direct | `body:0003` | 1,184 |

## 探针判定修订

首轮探针把所有成功取回都按分页信封断言，导致 5 个合法的单块 `text/units` 返回被误标失败。
检索结果本身已全部命中目标来源且排名第 1。随后按 `corpus_fetch` 文档中明确的两种成功形态
重新执行纯读取回，6/6 通过。该修订只修正探针判定，没有修改语料、检索实现或发布状态；
首轮过严结果仍保留在机器报告的 `probes_initial_overstrict` 中。

## 放行边界

该结果证明冻结 RC1 可以在不改变数据面的条件下连接当前生产语料，并稳定执行既有检索与取回。
它没有执行 8000 切换，因此不是生产切换完成记录。下一步仍是按
[切换与回滚 Runbook](v14-s4-cutover-runbook.md) 在维护窗口把 8000 从冻结 RC1 启动，并按
[上线监控方案](v14-s4-monitoring-plan.md) 观察；生产目标必须继续是 `postgres`，不得指向
`v14_s2_quote_corpus`。

完整字段、31 个采样点、8 个 build 明细和两轮探针记录见
[机器可读报告](v14-s4-canary-report.json)。
