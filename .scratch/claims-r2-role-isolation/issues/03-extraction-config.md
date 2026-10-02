# 03 · 独立 env 配置、冻结 profile 与模型 Adapter

Status: needs-triage
Execution: 未开始
Type: task
Plan: W2；R2-S2 的配置子项
Blocked by: 01
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

实现用户在 .env 中独立配置 M_extract 的路径；三个角色默认引用这一独立配置，不继承 M_main。

## 前置与外部门

01 已冻结加载位置、Adapter 契约和首轮支持 provider。可以与 02 做隔离实现/测试，但不因此提前宣布 R2-S2 放行；真实凭据和真实请求均不需要。

## 范围与预期文件

- `.env.example`、`plugins/corpus/structured/config.py` 的专用配置加载/冻结 profile、
  `plugins/corpus/claims.py` 的 build_default_llm 接缝、角色调用 Adapter；工件根目录键固定为
  `CORPUS_STRUCTURED_ROOT`，模型键固定为四个 `STRUCTURED_EXTRACTION_*`。
- 必要时复用 frontier_agent/infra 的配置/provider 能力，不改主线默认参数或全局环境变量。
- tests/test_corpus_structured_config.py，使用假环境、假凭据和录制请求。
- 独立变量为 STRUCTURED_EXTRACTION_PROVIDER、STRUCTURED_EXTRACTION_MODEL、STRUCTURED_EXTRACTION_BASE_URL、STRUCTURED_EXTRACTION_API_KEY。

## 验收条件

- [ ] 缺提取必需项时，即便 OPENAI_* 完整也返回未配置，零调用；不阻断确定性任务与已有结果查询。
- [ ] 仅从专用变量构造有效模型/端点/认证；不能逐字段回退到主线，也不能只是修改产物 model 标签。
- [ ] 三个角色可引用同一 profile；fake 多模型配置可分别命中不同 Adapter，角色与模型是独立维度。
- [ ] 调用前冻结非敏感配置指纹和凭据引用；运行中修改主线或全局 env 不漂移已开始任务，换模型新建运行身份。
- [ ] 日志、错误和快照均不含密钥或含密钥端点；真实 .env 不修改、不作为测试数据读取。
- [ ] SDK/包装器自动重试关闭；能力参数本地适配不算 attempt，实际兼容请求必须走 05 的获准调用入口。
- [ ] usage/响应模型不可得时保留未知，不伪造完整模型身份或零成本。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_config.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_config.py
```

测试断言调用参数与实际 Adapter 请求一致；仅校验 profile 对象不算完成。真实 provider 连通性留给 11。

## 非目标

不选择或购买模型，不填写用户凭据，不更换主线模型，不对未知 provider 增加自动 fallback。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
