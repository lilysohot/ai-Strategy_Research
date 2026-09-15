# R2 JSONL 两阶段开发验收报告

日期：2026-09-13  
结论：**JSONL 与分阶段协议解决了截断/整包丢失的一部分工程问题，但冻结开发门禁仍失败；R2 保持 partial，holdout 未运行，R3 不启动。**

## 冻结范围与用量

- 预算：`r2-jsonl-development-budget-v2.json`，SHA-256
  `550de1c02d3d40758a31a1c370a8606e71c0e0dc60e21c7aded1a2b2806b57cc`。
- 只使用原 4 份 development，金标文件 SHA-256 为
  `e8b541a6557189898bd8b86beab66af4b294cec19bc89c7d81e069f70ff0ac1b`；holdout 调用为 0。
- 冻结上限为 2 轮、每轮 16 次、累计 32 次；实际基线 7 次、纠偏 13 次，累计 **20 次**。
  12 次总量余量只是超限保护，两个轮次均已消费，不构成继续调参授权。
- 累计 token：prompt 51,044，completion 40,993；模型 `glm-5.3-flash`，单次 60 秒，输出上限
  8192 token。
- 基线报告：
  `material-semantics-runs/report-592e1ecf7ec47371dac296dae682868d67b70301c7f61445dae05a7dab0f56a8.json`；
  纠偏报告：
  `material-semantics-runs/report-37b7b37a59ce95acfdd585bb444d806f7ce7529e2a70068ea63a9e78c2cb5d6b.json`。

## 实现与审计

- `material-jsonl-v1` 将 speaker/item 与 relation 分成两阶段；每行独立 JSON，已完成行可以单独解析，
  item 上限为每包 30 条。
- `MaterialPacketRun.model_calls` 记录实际阶段调用；failed/partial 不再漏计。运行器按候选包 × 阶段做
  事前预算，并在重复轮次时于模型调用前拒绝。
- 失败或部分响应才写入本地忽略目录，8 份审计文件的内容哈希均复核一致，权限均为 0600；本文不
  记录原始响应内容。
- 基线审计证明模型返回的是完整 JSONL，但把 positive/negative、current/future、completed/planned
  等业务描述值写入严格枚举。纠偏只增加确定性别名归一化，并将抽取器升级到
  `material-semantics-7`；离线重放可保留基线 147 条 item 中的 146 条。
- JSONL 成功包全部为 completed，铜箔纪要 4 个包均未再发生 8192-token 截断。因此上一轮的“大对象
  截断”确为设计问题，已被本轮结构改造消除。

## 两轮开发结果

| 指标 | jsonl-baseline | jsonl-correction-1 | 门槛 |
|---|---:|---:|---:|
| item recall | 0/24 (0.0%) | 14/24 (58.3%) | >=90% |
| critical recall | 0/23 (0.0%) | 13/23 (56.5%) | 100% |
| semantic target accuracy | 0/24 (0.0%) | 13/24 (54.2%) | >=90% |
| attribution target accuracy | 0/24 (0.0%) | 9/24 (37.5%) | 100% |
| critical all-fields | 0/23 (0.0%) | 6/23 (26.1%) | 100% |
| source relation recall | 0/5 (0.0%) | 2/5 (40.0%) | >=90% |
| mapped relation precision | 无映射预测（记 100%） | 2/4 (50.0%) | 100% |

纠偏轮分样本结果：

- 公司研报：5/5 item、4/4 critical 命中；1 个语义类型和 1 个 polarity 不符，并产生 2 条已映射
  关系误报。
- 行业问答：模型把唯一 `summary_author` 的 `display_name` 输出为 null；speaker 失败关闭后，引用它的
  16 条 item 全部被拒绝，4 个目标均未命中。
- 个人交易复盘：4/4 item 和语义类型命中，但 4/4 speaker 归属类别不符，因此关键全字段为 0/4。
- 铜箔纪要：模型输出 104 条 item，但只命中 5/11 个目标；摘要展望、资本开支提问、主持人澄清、
  验证条件预测、混合听音确认和良率提问仍缺失。命中项另有 speaker、perspective、polarity 各 1 处
  不符；关系命中 2/4。

## 结构问题与设计问题的判定

本轮证据不支持把主要失败归因于“分析师文档结构”：公司研报包可完整处理，铜箔纪要 4 个结构包
也都完成，且不再截断。当前瓶颈主要在系统设计边界：

1. 输出 schema 的严格枚举与模型自然输出之间缺少完整适配；第一次纠偏已覆盖已观察别名，但
   `display_name=null` 仍会级联淘汰整包 item。
2. speaker registry 过度依赖模型同时生成 ID、显示名与角色；匿名作者/主持人应优先由结构层建立，
   模型只做受限引用。
3. relation 阶段没有先限制候选对，成功样本共输出 71 条关系，而冻结金标只匹配 2 条，表现出明显
   过建联。
4. 当前 precision 评分只统计“两个端点都映射到目标 item”的关系，其他关系不进入分母；因此报告的
   50% 是 mapped precision，不是完整的关系 precision。若要验收未支持关系，需冻结穷尽关系标注或
   独立负控，不能沿用当前选定目标集宣称完整 precision。
5. 铜箔纪要在 104 条输出下仍漏掉 6 个关键目标，说明继续扩大输出量无效；下一设计应在确定性话轮
   和问题边界上先生成候选槽位，再让模型填槽，而不是继续加 prompt 或 token。

## 停止条件与后续前置

两个冻结轮次均已消费，最终仍有关键归属、语义、polarity、关系误报和 failed packet，开发验收失败。
按预算停止条件关闭本轮，不运行 holdout，不推进 R3。

如用户未来再次授权 R2，必须先形成新的设计提案和确定性测试，至少包括：结构层 speaker/turn
registry、允许匿名显示名安全回退但不补造身份、候选槽位式 item 抽取、受限 relation candidate pair，
以及能真正衡量未支持 item/关系的负控或穷尽标注。不得直接把剩余调用上限当作新一轮预算。

## 工程验证

- Corpus 回归：357 passed。
- 新增/核心 material semantics：15 passed。
- Ruff：passed；本次模块 Pyright：0 errors。
- 全仓 Pyright 仅因可选部署依赖 `gradio` 未安装，在 `deploy/huggingface/app.py:26` 报
  `reportMissingImports`；不是本次变更引入。
- import smoke stage 1：336/336。
- symbol closure：435 files、0 missing。
- R1 金标：passed；44/44 引文，holdout 碰撞 0。
- 重复 `jsonl-correction-1`：在模型调用前拒绝。

