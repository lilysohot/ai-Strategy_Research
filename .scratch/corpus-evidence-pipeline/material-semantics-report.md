# R2 材料语义抽取开发验收报告

日期：2026-09-13  
结论：**实现已形成，但冻结开发门禁未通过；R2 保持 partial，留出集未运行，R3 未开始。**

## 本轮实现

- 新增 `plugins/corpus/material_semantics.py`：在既有不可变 `EvidenceRun` 上生成内容寻址的
  `MaterialRun`，覆盖材料类型、研究领域、表达者、事实/预测/观点/行为、问答、条件/风险、视角、
  否定、行为状态、时间框架、显式关系和逐字证据。
- `CorpusService.understand_material` 可接收现有 evidence run ID，也可直接接收未入库文件路径。
  直接路径默认不入库、不保存 EvidenceRun、不访问数据库。
- 每条 item/关系引文必须在当前 packet 唯一回取；未声明表达者、系统归纳冒充来源、推断关系或
  整包无有效 item 时失败关闭。单个额外歧义引文只丢弃该记录并留下诊断，不拖垮其他合法记录。
- 既有候选器新增无数字多人问答召回；旧数字、评级、个人交易和噪声规则不另建一套分支。

## 用户新增纪要

`data/corpus/5月：锂电铜箔和电子铜箔.md` 未入库，但现有解析器可直接读取。运行时身份为
`doc_id=undated_80b5a290`、`source_rev=80b5a290df3d2ade`；类型确定性识别为
`conference_minutes`，领域为 `industry`。文件名只有“5月”，无法支持年份或精确日期；主持人、
专家和多数投资者没有实名，均保留 unknown。

“未入库”不是本次失败原因。最终运行中该纪要第一个 packet 完成并产生 35 个有唯一引文的 item；
第二个 packet 的模型响应为不完整 JSON（`line 71 column 376`），因此按停止条件失败关闭。其冻结
目标只匹配 3/11，后半段良品率问答、铜冠转述、尾号 6161 问答等未达到门禁。

## 冻结开发验收

最终模型运行：`glm-5.3-flash`，每文档最多 2 次正文调用，单次超时 60 秒，未调用同花顺或数据库。
最终原始运行报告：
`material-semantics-runs/report-d3f55ef784c1e559550fb6ab7475420f2d6e3b64bcc1387e95dbfd0419e96102.json`。
修正汇总分母后的零调用重放报告：
`material-semantics-runs/report-72828df3f6da523240cf6b56f45c676b377ca906389c0c214c1d21951304283b.json`。

| 开发样本 | 目标 item | 命中 | 关键命中 | 完整性 | 主要失败 |
|---|---:|---:|---:|---|---|
| 公司研报 | 5 | 5 | 4/4 | complete | 公告转述归属错误；目标价被归为 opinion |
| 行业问答研报 | 4 | 0 | 0/4 | failed | 模型输出非法 semantic_type，整包失败关闭 |
| 个人交易复盘 | 4 | 4 | 4/4 | complete | 行为 statement_role 未达到冻结标注 |
| 铜箔电话交流纪要 | 11 | 3 | 3/11 | failed | 第二 packet JSON 无效；后半段问答未进入产物 |

按全部开发 gold 的真实分子/分母汇总：

- item recall：12/24 = **50.0%**（门槛 90%）。
- critical item recall：11/23 = **47.8%**（门槛 100%）。
- semantic target accuracy：11/24 = **45.8%**（门槛 90%）。
- attribution target accuracy：11/24 = **45.8%**（门槛 100%）。
- critical all-fields accuracy：5/23 = **21.7%**。
- `source_explicit` 关系 recall：1/5 = **20.0%**（门槛 90%）；对已映射 gold 端点的
  precision 为 100%。gold 是选定目标而非全文穷举，额外合法关系不计误报。

三个完整开发轮次各 5 次调用，另有 3 次铜箔纪要诊断调用，共 **18 次**，未超过 24 次开发预算；
已使用基线加两次规则修订。最终开发门禁仍失败，故按冻结停止条件停止调参，不运行 2 份独立留出，
也不把局部成功解释为 PR-DATA-10 通过。

## 确定性验证

- 新增材料语义测试：8 passed。
- Claims v2、Evidence pipeline、统一接口与布局召回相关回归：76 passed（包含上述 8 项）。
- Pyright：0 errors；stage-1 import smoke：336/336；symbol closure：435 files、0 missing。
- 未运行 `preflight.py`，因为它会新增真实模型调用，而本轮已按开发停止条件终止调用。
- 金标结构/来源/引文复核：passed；4 development + 2 holdout、37 items、34 critical、7 relations、
  44 aligned quotes，留出历史碰撞 0。

金标在实现前检查时修正了两项项目契约错位：`source_rev` 改为项目既有的 16 位身份，并另存完整
`source_sha256`；行业研报冻结第 3 页不能支持作者姓名“马太”，故改为 unknown。两项都有确定性
证据，不依据模型得分改写目标语义。

## 当前阻塞

R2 不能进入 completed，也不能推进 R3。继续需要新的实现策略，而不是第三轮提示词调参：优先考虑
约束 JSON schema/分段输出、逐记录容错解析，以及对问答和交易结构做确定性预分段后再抽取。任何
后续修复必须重新冻结新的开发预算；现有两份 holdout 在开发规则重新冻结前不得运行。

后续已按用户授权完成一次结构重设计预算，分包和逐记录容错已落地，但两轮开发门禁仍失败；状态、
调用用量和新阻塞见 [结构重设计报告](material-semantics-redesign-report.md)。
