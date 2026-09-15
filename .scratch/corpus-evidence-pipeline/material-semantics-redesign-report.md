# R2 材料语义结构重设计开发报告

日期：2026-09-13  
结论：**工程改造已落地，但冻结开发门禁仍未通过；R2 保持 partial，holdout 未运行，R3 不启动。**

## 冻结范围与用量

- 预算：`r2-redesign-development-budget-v1.json`，SHA-256
  `2c05f12217a1f527a2912c12b5cedb900a9bfa21de8985c7259e22409a8903d8`。
- 只使用 4 份 development；holdout 调用为 0。
- 冻结上限为 2 轮、每轮 8 次、累计 16 次；实际运行 2 轮，每轮 6 次，累计 **12 次**。
- 调用 token：prompt 36,036，completion 42,439；模型 `glm-5.3-flash`，单次 60 秒，输出上限
  8192 token。
- 纠偏轮原始报告把 `partial` packet 漏出调用计数，显示 5 次；按 6 个 MaterialPacketRun 产物
  复核后实际为 6 次。运行器已将 `partial` 纳入 attempted calls，并从产物重算历史预算。

## 实现改造

- `evidence-layout-4`：分包优先在新问题、编号问题和发言者话轮前断开；4100 字下铜箔纪要由原来的
  8000 字两包改为 3833/4022/3960 三个完整话轮包，不再从专家长回答中间起包。
- `material-semantics-5`：明确 statement/speech role 优先级、匿名角色、行为、公告、目标价、摘要、
  混合话轮、尾号提问、事实后接展望及 quoted evidence 关系规则。
- speaker/item/relation 改为逐记录验证；坏记录不再清空同包良品。
- 截断对象可抢救已完整的数组记录，但 packet 必须标为 `partial` 并进入 omitted coverage，不能伪装
  complete。
- 评分归属允许 gold role 与输出 display name 的同类交叉匹配，并把 identity_status 纳入关键字段；
  旧的“行业专家”与“专家”不再被误判为不同表达者。
- 运行器绑定预算文件、金标文件 SHA、development sample ID、模型和轮次；重复轮次在模型调用前
  拒绝。

## 两轮开发结果

| 指标 | 改造前最终 | redesign-baseline | redesign-correction-1 | 门槛 |
|---|---:|---:|---:|---:|
| item recall | 12/24 (50.0%) | 20/24 (83.3%) | 17/24 (70.8%) | >=90% |
| critical recall | 11/23 (47.8%) | 19/23 (82.6%) | 16/23 (69.6%) | 100% |
| semantic target accuracy | 11/24 (45.8%) | 18/24 (75.0%) | 16/24 (66.7%) | >=90% |
| attribution target accuracy | 11/24 (45.8%) | 19/24 (79.2%) | 17/24 (70.8%) | 100% |
| critical all-fields | 5/23 (21.7%) | 12/23 (52.2%) | 14/23 (60.9%) | 100% |
| source relation recall | 1/5 (20.0%) | 2/5 (40.0%) | 1/5 (20.0%) | >=90% |
| mapped relation precision | 100% | 66.7% | 100% | 100% |

基线原始报告：
`material-semantics-runs/report-c356a3c9760f955beb6de1b0cd41be9c75123db294cfc2a3aa9e305c5706ad34.json`。
归属评分零调用修正：
`material-semantics-runs/report-b914746a69465e8f1084da0796461f1541cff72d8733326641a90ce398835e13.json`。
纠偏轮原始报告：
`material-semantics-runs/report-8a5ff4c2ab4d9377c342d70f5780fc234820809ccc0751ac8234edfff500a109.json`。

样本结论：

- 公司研报：纠偏轮 5/5 item、4/4 critical 全字段通过。
- 个人交易复盘：两轮均为 4/4 item、4/4 critical 全字段通过。
- 行业问答：基线 4/4，只有一项 polarity 不符；纠偏轮返回的 items 均未通过证据验证，整包失败。
  当前失败产物没有保留逐条原始拒绝原因，不能再靠提示词判断根因。
- 铜箔纪要：基线 7/11，纠偏轮 8/11、critical 全字段 6/11；第三包生成 54 个可抢救良品后达到
  8192 token，故正确标为 partial。摘要、主持澄清和混合听音话轮仍遗漏；关系仅 1/4。

## 停止与后续条件

两次冻结轮次均已消费，最终轮仍有 failed/partial packet 和关键遗漏，故按停止条件结束。剩余 4 次
是总量护栏余量，不是第三轮授权。不得运行 holdout，也不得推进 R3。

若继续 R2，需要另行冻结新的结构开发预算，并先改变内部响应协议：以短 JSONL/逐 item 对象替代
单个巨大 speakers+items+relations 对象，原始失败响应做受控审计留存，item 与 relation 分阶段，
每批设置明确记录上限。不能再以增加 prompt 条款或提高 token 上限作为主要修复。

后续执行记录：上述 JSONL 两阶段方案已在独立冻结预算下实施并完成两轮 development 验证；虽然
消除了成功包截断，最终门禁仍失败。当前结论以
[JSONL 两阶段报告](./material-semantics-jsonl-report.md) 为准。

## 确定性验证

- 相关回归：143 passed。
- 新增/核心定向：29 passed。
- Ruff：passed；Pyright：0 errors。
- import smoke stage 1：336/336。
- symbol closure：435 files、0 missing。
- R1 金标：passed；44/44 引文，holdout 碰撞 0。
- 重复 `redesign-correction-1`：在模型调用前拒绝。
- 未运行 preflight：它会产生额外真实模型调用，且开发停止条件已经触发。
