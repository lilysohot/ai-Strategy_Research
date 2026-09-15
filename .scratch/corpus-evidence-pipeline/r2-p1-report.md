# R2 P1 执行报告：Interface 冻结与有限规划可行性

日期：2026-09-14。用户授权：按清单执行下一步，即 P1；不启动 P2 或新模型轮次。

## 结论

**P1 设计交付完成，合成有限规划检查通过，可进入 P2 的零模型验收器实现。**
不代表已经实现生产新 R2，不代表通用自动原子化、真实研报忠实度或 CLI 链路通过。
P0-A 保护校验通过，P0-PG 继续未验证，P0 总体 partial；v13 原失败与关闭预算不变。

本轮没有生产代码改动、真实模型/judge/市场调用、真实入库、生产 PG 连接或 holdout 原文读取。
没有读取开发 gold 生成义务，也没有把代理判断签成人工裁决。公开合成例子不包含私有会议原文。

## 交付与冻结

- [P1 Interface/终态/评分契约](../../docs/plan/r2-p1-interface-contract.md)：定义调用顺序、坐标/身份、
  容量、未知与失败语义、运行时/开发评分分工、逐轴阈值、粒度裁决、兼容/例外表和 P2 移交。
- [可执行 planner 规格](p1_planner_spec.py) 与 [65 项测试](test_p1_planner_spec.py)：仅标准库纯输入/
  输出实现，不导入生产提取器、模型、数据库或 gold；不能被生产层引用来形成第二条抽取链。
- [测试逐项记录](p1-validation-results.xml)：JUnit XML 保存实际测试名称、结果及耗时。
- [冻结清单](r2-p1-contract-manifest.json)：绑定契约、规格、测试、结果与旧路径复核快照。

本清单不是 budget JSON，不提供任何调用额度。外部固定 SHA-256：

```text
r2-p1-contract-manifest.json
a9477f7281287b0ce78b3fcc978b88fa5d48f5312094851e4e00d67cf2370603

沿用 P0 baseline-manifest.json
4e2c45ce216a942137f60b863e236ae46f3a8870317ebdbe9ead6342b4698076
```

## 本次实测

| 检查 | 实际结果 | 不能推论 |
|---|---|---|
| 六组结构、12 个合成场景 | 并列、嵌套条件、跨段问答、否定、无标签对话、寒暄均按显式预期保留；危险拆分转 unresolved | 不能证明未读真实文档已原子化 |
| 每场景删除叶子负控 | 全部拒绝，字符覆盖不能冒充无遗漏 | 输出转述语义 mutation 尚在 P2 |
| 坐标/绑定/输入负控 | 重复引文在不同坐标合法；错版本/错坐标/漂移/重叠/重复包拒绝 | 合法证据不证明内容忠实 |
| 容量 | 精确容量通过；超 root/children/total/字符/深度拒绝，无截断 | 不是模型 token 或 9 次调用可行性证明 |
| 伪造完成/重算计划 | 不允许 planner 声称语义通过；缩范围或提高容量重算 hash 不能替换外部固定 plan | 不替代 P2 预算崩溃安全实现 |
| 新测试 | **65 passed、0 failed、0 skipped**，0.10 秒 | 不把工程测试数当业务指标 |
| 新文件 Ruff | check、format 通过 | 未重跑全库 pyright/全部工程测试 |
| P0 源码/资产/环境 | 执行前后校验通过，受保护代码/测试仍逐字相同 | PG 集成门依然未验证 |
| R2 禁用旧路径重放 | 新进程快照与 P0 三份原快照相同 | 只覆盖原冻结行为夹具，不证明全类目语义非回归 |

新快照：
`p0-baselines/baseline-4e2c45ce216a9421/snapshot-p1-r2-disabled.json`

SHA-256 与 P0 原快照一致：
`847f3381a5c2f86a86b0efcde6ae79efceba7e9662e964962e69071a06b0133b`。

该快照沿用原 P0 的 in-memory EvidenceRun/claims、临时 SQLite、固定 HTTP MockTransport 和真正旧
service CLI 代码路径；example.test 日志不是实际网络请求。生产数据库入口与 socket 均被阻断。
本轮未重复计算“605+18+169”测试数；旧测试结果保留原日期/范围，本次新增的是65项规格测试及一次快照。

## 可行性判断与仍需否证的问题

1. **保留有限路线，但不再宣称句法等于语义。** 系统可以固定来源、有限任务和复核账本，无须解锁
   公共 parser；复杂并列/嵌套条件可无损返回 unresolved。结构候选仍必须核验是否恰好一个命题。
   planner 的保守风险信号不完备，未知表达不能通过“没命中规则”自动成为已验证原子命题。
2. **运行时可用不等于开发通过。** 新文档无 gold 可以给可回取的部分产物；内容忠实度未知明示。
   运行时不会读取 gold 给自己认证。P2 EvaluationReport 必须能拦编造 text、否定/条件翻转等输出级反例。
3. **原子分母不能偷换。** 旧35项含较长总结；P3 必须先列粒度差异并裁决，不能直接把新的候选数
   作为评分分母。代理只能提出建议；尚未产生任何新人工批准。这可能成为后续真实卡点。
4. **容量有界不等于成本合适。** 全 support 与相邻 context 的展开可能很大，当前上限不是模型批次
   设置。P3 必须报告真实四类来源的 unresolved 比例、覆盖、人工量、token/批次成本，才评估是否继续。
   本轮没有用合成12场景宣称那些比例已合格。

因此 P1 出口限于“契约可表达，保守有限规划/负控通过，无需修改公共 parser”；不是对模型方案的
最终投资承诺。若 P3 发现多数内容必须人工拆分/裁决，或新协议原始回放资产不足，按既定停止点报告，
不通过降低阈值或无限增加人工工作追求绿灯。

## 复核命令

先核验以上外部固定 manifest SHA 和 manifest.files 内每个文件 SHA，再执行：

```bash
uv run pytest .scratch/corpus-evidence-pipeline/test_p1_planner_spec.py -q
uv run ruff check .scratch/corpus-evidence-pipeline/p1_planner_spec.py \
  .scratch/corpus-evidence-pipeline/test_p1_planner_spec.py
uv run python .scratch/corpus-evidence-pipeline/p0_baseline.py verify \
  --manifest .scratch/corpus-evidence-pipeline/p0-baselines/baseline-4e2c45ce216a9421/baseline-manifest.json \
  --sha256 4e2c45ce216a942137f60b863e236ae46f3a8870317ebdbe9ead6342b4698076
```

重跑不要覆盖已冻结 JUnit XML；需要保存新结果时另选文件名。Python/依赖环境继续绑定 P0，未装新包。

## 下一步

按清单进入 P2：**先新版 scorer + 输出 mutation，后 R2 私有处理**。G0—G3 反例、fake 关系协议、
无隐式 I/O、预算预留崩溃与原始响应留存故障都需要真正测试；不能把本轮规划器检查复用为那些门已过。
公共保护仍无新增例外，P2 修改白名单应前瞻登记；P3 非回归与裁决完成前，P4 新模型预算不创建。
P0-PG 在 P6/V1 前仍需隔离环境；本阶段不要求提供生产密钥或新纪要。

本次采用 codebase-design 的 Interface/Seam 方法，将纯规划、外部执行 Adapter、运行时校验和开发
评测的职责分开；保留旧入口及所有公共安全测试，未把可执行设计规格接入生产。
