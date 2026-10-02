# 09 · react/tui 产品接线与零模型端到端验收

Status: needs-triage
Execution: 未开始
Type: task
Plan: W5 回放；R2-S3
Blocked by: 08
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

证明从快照到报告校验的最小链路确实经过用户使用的 react/tui 入口，而不只是内部函数可调用。

## 前置与外部门

08 已验收；01—08 的传递依赖证据齐全。主计划 S3 的 I3 等外部门另行核对；本票回放通过不单独宣告阶段放行。主线和抽取都使用 fake/replay，不需要用户真实 .env。

## 范围与预期文件

- plugins/tools/__init__.py、workflows/stateful_react_agent/profiles/tui.yaml、nodes/main_agent.py、apodex/profiles/react.yaml 的实际绑定路径。
- plugins/corpus/research_discipline.py、corpus_manifest.py 的提示词/工具说明。
- tests/test_corpus_structured_react_replay.py、受控 CLI/loop 回放夹具。
- 在明确实验 profile/配置下接通只读工具 `corpus_semantic_query`；根目录只从
  `CORPUS_STRUCTURED_ROOT`/显式参数取得，不擅自为所有用户默认开启，其他产品入口保持未验证。

## 验收条件

- [ ] 录制真实 workflow 的工具名单，查询、原文回退和伴随报告清单按契约绑定；不在终端 profile 重复维护无效 tools 列表。
- [ ] 充分语义证据成为合法引用路径，旧 search snippet 仍不可直接引用；提示词不强迫每条再 fetch。
- [ ] 通过正式调用链生成/保存/发布合成两路工件，关闭写端，从新研究 run/cwd 查询并经过全部后处理进入主线消息。
- [ ] 消费观察者核验送达，主线回放提交报告清单，经 pending/确认/最终锚点检查，正例最终 verified。
- [ ] 仅新查询活动不 skip，无后台模型请求、无真实主线模型请求，充分证据路径无例行 Agent fetch。
- [ ] 缺脚注、坏句柄、预算裁剪、目录不可见、撤回、resolver 故障分别触发对应缺口/修订/原文回退；不能以未检查状态出具成功。
- [ ] 原文研究路径回归，关闭新查询后旧入口仍可运行；市场响应固定，不以真实行情变化影响结果。
- [ ] 输出验收 trace、工具名单、模型/网络拒绝记录、调用次数、发布/报告验证结果及输入版本；标为“回放接通”，不是“真实模型接通”。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_react_replay.py tests/test_corpus_cli_isolation.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py -q
uv run python tools/import_smoke.py --stage 1
uv run python tools/import_smoke.py --stage 2
uv run python tools/check_symbols.py
```

另对实际改动执行 Ruff、类型检查。所有回放请求由假 Adapter 接收，业务网络/生产库禁止；不能手工往账目填 delivered。真实 preflight 留给 11，不在本票执行。

## 非目标

不支持全部 Agent Team/终端路径，不进行真实模型或独立留出试验，不把文件回放当生产 PG 验收。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
