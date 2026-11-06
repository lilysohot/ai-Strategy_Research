# 团队协作评估集 v1.1

评估对象是团队的派工、取证、上下文交接、核验、恢复与最终交付。
当前 35 个公开案例：29 个协议回归、6 个固定资料的真实模型团队任务。
保留首版全部 20 个案例和原有验收标准；v1.1 新增本次运行的修复链与协议对照。
它与 `benchmarks/team_synthesis` 互补：后者只评估固定成员报告的综合写作，
本目录的 frozen 层运行生产 `main_agent_node`、AgentBus、成员循环、任务板和交付门禁。
首轮失败基线保持不变，后续修复结果单独记录，不覆盖历史结果。

## 案例与验收

`cases.json` 是版本化目录。每项包含来源运行、目标、维度、数据分组和执行入口；
frozen 项还包含问题、来源正文、逐项 rubric 和预算。历史问题改编为虚构材料，
避免将真实运行中的未经证实观点固化为真值；大段私人原文不复制进 Git。

development 表示已知故障；transfer 是公开的跨情景和正向对照，**不是未见留出集**。
真正盲测应在调试结束后由独立维护者准备，并冻结到新版本目录。
不能以改写 rubric、放宽预算、删除失败案例的方式证明生产修复有效。

首版维度：编排、上下文、证据、工具、核验、恢复、交付。F04 是正向对照：
在明确题设内应该推荐 B（120 元、99.8%）；空泛免责声明不能获得通过。
F05 允许有用的部分交付，不能强求伪造完整结果。

## 1. 协议层：无需模型或网络

在仓库根目录、Linux/WSL、已有 uv 环境执行：

```bash
uv run python -m benchmarks.team_workflow.run run \
  --layer protocol --out results/team-protocol-001
```

复用已有 pytest 回归；P15 是新增的生产链路探针：
`ContentAcquisitionObserver -> AgentLoopResult -> bind_checks` 是否携带网页原文。
探针保留真实断言，不使用 xfail，不把已知缺陷改成成功预期。
探针位于本评估目录，普通 pytest 不会默认收集；显式评估会执行它并返回失败。
P16–P21 覆盖 6d4a 运行中的 DSML 恢复、修订候选派工预检、复核上下文、
最新性同义表达、恢复后仍拒绝无依据 PASS，以及交付批量反馈。
P22 覆盖畸形、越权、重复参数、嵌套调用和有界协议恢复，直接运行生产循环。
P23–P25 固化运行 `18937dbdabb1401296a685aeaa747c0b` 暴露的三条链路：批量网页逐页归因、
按待核验主张选择后置证据，以及阻止失败核验中的绝对化结论改写后进入部分交付。
它们属于已知问题及公开对照，不能作为独立盲测成绩。
P26–P29 延续运行 `3b30ebfd2e214ca19cc60e97ec36c12c`：短直接证据预算、
正文核验标签范围、无损字段错层恢复，以及部分检查超时后的独立重试。
F06 用虚构资料检查观测日期、混合预测期限与条件性因果判断，未修改既有题目的 rubric。
这轮回传先保留相关的短正文，再为长文分配有界摘录；它改善证据可见性，
不代表每条主张的证据都已充分。字段容错仅移动错放的 `unresolved_issues`，
保留原始参数供轨迹审计；冲突副本、非空缺陷列表配 PASS、范围不匹配仍然拒绝。
核验标签门禁覆盖本次暴露的明确表述及其对照，不承担任意改写的语义审查。
因果、概率及新增综合结论仍需要模型核验；协议通过不能替代 F06 等端到端验收。
本轮 [修复与验证记录](REPAIR-3B30-2026-11-06.json) 保留了协议通过结果与真实模型执行失败，
没有把首轮推理保护触发、重试超时的 F04/F06 算作通过。
详见 [本轮修复与验证记录](REPAIR-6D4A-2026-11-05.md)。
所有选中案例都继续执行，结束后任一失败、错误、跳过或缺测均返回退出码 1。

## 2. 固定资料层：真实团队与真实模型

```bash
# 先执行少量正常/缺陷场景；默认按案例目录顺序串行运行。
uv run python -m benchmarks.team_workflow.run run \
  --layer frozen --case F01 --case F04 --profile default \
  --out results/team-frozen-001

# 全部六题，各重复两次；最多十二次团队运行，不是十二次模型调用。
uv run python -m benchmarks.team_workflow.run run \
  --layer frozen --repeats 2 --out results/team-frozen-002
```

使用已有模型配置与凭据。每题独立进程，默认并发 1，题内仍可真实并行派工。
固定资料层默认连续两项执行错误后停止启动后续样本，可通过
`--max-consecutive-errors` 调整；质量失败不触发该规则。剩余样本记为 unassessed，
仍保留在分母中，并写入 `batch_stop.json`。协议层始终执行全部选中案例。
正式案例每题预算 600 秒；工作流明确收到这一预算，外层再设清理宽限并终止进程组。
初始 300 秒校准配置的研究窗口仅 59 秒，派工窗口仅 11.2 秒，不适合作为正常协作
语义基线，已保留校准工件并明确废止该配置。首轮配置研究窗口 359 秒、派工窗口
254 秒。随后修复生产阶段预算重叠后，同一 600 秒配置的研究窗口为 341.2 秒、派工
窗口约 236.96 秒，完整保留核验和交付时间；总预算未增加。
启动前若有效派工窗口不足 90 秒，直接返回配置错误，
不消耗模型调用。`settings.json` 的 `budget_layout` 记录实际窗口，环境中的更短平台
上限也会参与计算。见 [首轮基线](BASELINE-2026-11-05.md)。
只注册生产协调工具及保留生产 schema 的固定 `web_search`/`web_fetch`：
任意搜索返回小型固定来源目录，fetch 仅接受目录中的精确 URL；未知 URL 与
预设不可用页返回失败，无真实网络回退。未注册 shell、下载、数据库或文件读取工具。
因此模型能自主决定怎么派工、检索、复核；但本层**不测真实检索排序和网络服务质量**。

模型只看到问题、来源目录以及实际工具返回。rubric、案例来源、分组和预期结论
不会注入提示词。真实 LLM 请求仍会发送这些虚构材料给已配置的模型服务。
不需要启动 Web 服务，不写用户业务会话，不重启生产服务。

## 3. 真实工具验收与运行诊断

真实工具端到端继续使用已有 Web 会话或 public subprocess runner，不增设另一套生产入口。
发布前以同一问题、同一预算运行真实工具案例，保留完整 run 工件，并记录来源版本。
网络或资料内容变化时不能声称与 frozen 结果是严格配对实验。
本工具可读取既有 Web run 的标准轨迹，提取时间、调用与排队指标：

```bash
uv run python -m benchmarks.team_workflow.run inspect \
  --run /path/to/web/runs/RUN_ID --out results/run-metrics.json
```

这只是观测，不自动宣称内容正确。首次研究报告时间不等于首次有用结论；
并行模型耗时总和不是总墙钟耗时；排队延迟由派工尝试与成员启动时间匹配估算，
拒绝派工会影响估算。无法取得的 usage 保留缺失计数；未配置价目时不计算美元成本。

## 输出与评分

每次必须使用新输出目录，拒绝覆盖或静默复用。输出包括：

- `manifest.json`：完整案例快照、目录哈希、代码和 profile 文件哈希、Git 提交、profile 名、重复次数。
- 每个样本的 `source.json`：该样本开始时的代码指纹，暴露运行期间代码变动。
- 每个样本的 `input.json`、`execution.log`、`result.json`。
- 协议层的 `pytest.xml`；固定资料层的 `worker.json`、`metrics.json`、完整轨迹。
- `settings.json` 在模型调用前保存非敏感模型采样设置、有效 agent 配置和实际阶段预算。
- `worker.json` 保留实际答案与 report_contract；不把模型自报 PASS 当成外部评估通过。
- `summary.json` 和 `report.md`：所有样本与分位耗时；缺测不从分母消失。

状态分别为 pass、fail、error、unassessed、needs_review、missing。
协议测试通过不代表团队语义通过；工作流内部 PASS 也不是外部评估的 PASS。
固定资料任务完成后先检查空答案、未执行成员、任务扩张、时间与输入预算；
通过这些机械检查仍为 needs_review，必须按 rubric 检查事实支持、独立核验和全文一致性。
任务扩张按实际接受的研究 job 计数，核验 job 与被拒绝的派工重试不计入此预算；
重试次数仍保留为诊断指标。修正机械评分器后可用 `report --rescore --out ...`
重新读取已完成工件，不重新调用模型；旧评分保存为 `assessment-before-NNN.json`。
已有评审的样本拒绝机械重评分。
预算值是首版工程目标，不是已验证的服务 SLO；修改后必须重新建立可比基线。

人工评审文件格式：

```json
{
  "reviewer": "评审者身份",
  "review_type": "human",
  "worker_sha256": "run.digest(worker.json解析后的对象)",
  "case_sha256": "run.digest(input.json解析后的对象)",
  "criteria": [
    {"verdict": "pass", "evidence": "指出答案段落及对应来源/轨迹"},
    {"verdict": "fail", "evidence": "指出具体错误及对应来源/轨迹"},
    {"verdict": "unassessed", "evidence": "说明尚不能判断的原因"}
  ]
}
```

```bash
uv run python -m benchmarks.team_workflow.run review \
  --out results/team-frozen-001 --sample F01-r1 --file review.json
uv run python -m benchmarks.team_workflow.run report --out results/team-frozen-001
```

每项 rubric 必须有裁决和证据说明，评审绑定准确答案与案例哈希，不能覆盖机械硬失败。
每次评审保存到独立 `review-NNN.json`，不覆盖此前评审记录。
若使用模型辅助评审，必须使用 `review_type: model`：保存 diagnostic_verdict，
状态仍为 needs_review，模型评审不能使发布门禁变绿。
不要只比较一个综合分：先看硬失败是否新增，再看覆盖、有效分析与时间/token 的变化。
相同案例重复运行不是新增独立样本；小样本 p90 仅作诊断。

修复后在新目录重跑，再比较：

```bash
uv run python -m benchmarks.team_workflow.run compare \
  --before results/team-protocol-001 --after results/team-protocol-002 \
  --out results/team-comparison.json
```

案例目录（包含预算）或 profile 名变化时拒绝称为配对实验。有效配置变化另行标注；
缺失样本保留为 missing，旧 pass 变为错误、缺测或待评审也会作为退化提示。

## 修改与维护流程

1. 新故障先做一个最小可复现案例，保存正确期望与明确来源；已有问题优先扩展现有回归。
2. 跑协议层，记录失败基线；生产修复后使用相同案例与预算重跑。
3. 影响模型决策、提示词或交接时跑对应 frozen 案例，并复核原文与最终正文。
4. 复用 `benchmarks/team_synthesis` 的固定报告与匿名评审作为综合写作补充，不能替代团队测试。
5. 发布前增加未参与调试的问题与真实工具运行；对照同版案例、模型、预算和配置。

手动 GitHub Actions 工作流 `Team workflow evaluation` 执行协议层并保留工件。
任何红项都会使工作流失败，不应加 continue-on-error 隐藏。
首轮 P15 红项已通过生产网页交接修复转绿；原始失败基线仍保留。
评估器自身完整性测试位于 `tests/test_team_workflow_eval.py`，随普通测试运行。
