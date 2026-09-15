# 16 宏观 M1：不可变输入与审核记录

Status: completed
Execution: model-layer-accepted — production computation remains disabled

用户明确要求完成 [M1](../../../docs/plan/corpus-macro-contract-implementation.md)。
实现：`plugins/corpus/macro_models.py`、`plugins/corpus/macro_verification.py`。
说明：[模型、信任范围与接入方式](../../../docs/corpus-macro-input-models.md)。

## 验收映射

- 发布事件、版本、预期快照、观测和审核记录均不可变；嵌套 tuple/冻结模型，未知字段拒绝。
- 统计月、实际/预期、observed/forecast、岗位/月变化/同比/修订、SA/NSA 独立编码。
- 显式 UTC 偏移时间；未知时间和数值不填补，稳定 blocked/null/原因码结构。
- 原始 value_raw/unit_raw 保留；有限 Decimal 换算，万/万人需受控岗位映射审核记录。
- 内容身份和序列化可重放，冲突 envelope、重复 ID/JSON 字段拒绝；旧 run 只读引用兼容。
- 应用侧 authority 登记并核对审核对象/范围/版本；独立导入 JSON 不取得信任，不开放给模型自行审批。

M1 不部署认证或持久核验系统，不实现 M4 的字段真伪/时序配对核验，不注册宏观计算公式。
本轮仅使用合成测试，没有实际数据审核或 M2/M3 的外部数据访问。

## 验证记录（2026-09-13）

- 新增 M1 测试：47 passed；完整 Corpus 子集：282 passed。
- 新增模块 Ruff 检查/格式检查通过，Pyright 0 errors / 0 warnings。
- import_smoke stage 1：333/333；stage 2：382/382。
- check_symbols：432 文件，0 missing。
- preflight：一次真实廉价调用通过；JUDGE_API_KEY/JUDGE_BASE_URL 未设置，未运行模型评审。
- 未运行全仓库测试；M2—M6 和独立真实事件验收仍待执行。
