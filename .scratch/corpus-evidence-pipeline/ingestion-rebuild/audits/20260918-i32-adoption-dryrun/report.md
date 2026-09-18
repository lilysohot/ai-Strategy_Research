# I3-2 采纳干跑报告（2026-09-18）：AI 补证包 → 新金标版本 → 重映射 → 裁决件 → 门

> **本目录全部是干跑产物，不是批准，也不是金标。**
> 未写 `i3-2/evidence-targets-decisions.json`、未写 `i3-2/evidence-targets-approved.json`、
> 未改任何冻结件（`source-gold-frozen.jsonl` / `query-gold-frozen.jsonl` / `guards/i3.json` /
> `freezes/freeze-manifest.json` / 正式候选 / `approval-report.json` 字节均未变，见
> [protected-artifacts-check.json](protected-artifacts-check.json)）。

> **更新记录（2026-09-18 晚）**：署名口径更新为"具名审核人 **xyl**（已全文审核并确认署名）+
> `ai_assisted: true`（AI 辅助核验，非人类签名）"。全部产物已按此重跑，门的结论不变
> （机器口径 18 阻断行 / 对照口径 2 阻断行）。

## 1. 结论（三句话）

1. **材料版本可以建**：23 条冻结槽位逐字节保留，采纳 13 个新槽位 / 49 条新条目（逐条与复核报告的
   页内切片对账通过）；负例近似命中 7 条隔离到
   [source-gold-nearmiss-library.jsonl](source-gold-nearmiss-library.jsonl)，**不进证据映射池**。
2. **重映射符合预期**：目标 54 → 82（必需 44 / 补充 20 / 待批准锚点 18），`blocked` 2 → 1（只剩
   `macro-004`）；40 项要件裁决与 r25 一致（同一批要件，锚点换到了新补证条目上）。
3. **门仍未开**：按机器可核的口径 `ready=false`，剩 **17 项要件**需要具名人工动作；若 U **逐项确认
   同义**（协议允许、机器只核出处），则只剩 **1 项**（`industry-008-02` 的日期锚点，原因见 §5.3）。

## 2. 阶段与产物

| 阶段 | 脚本函数 | 产物 |
|---|---|---|
| A 建版本 | `build_source_gold` | [source-gold-v4-candidate.jsonl](source-gold-v4-candidate.jsonl)、[release-manifest.json](release-manifest.json)、[source-gold-nearmiss-library.jsonl](source-gold-nearmiss-library.jsonl) |
| B 重映射 | `remap` | [candidates-v7-dryrun.json](candidates-v7-dryrun.json)、[review-v7-dryrun.md](review-v7-dryrun.md)、[adjudication-v7-dryrun.md](adjudication-v7-dryrun.md) |
| C 转裁决件 | `convert` | [decisions-dryrun.json](decisions-dryrun.json)（正式 schema、`dryrun: true`） |
| D 跑门 | `gate` | [gate-dryrun.json](gate-dryrun.json) |
| C2/D2 对照 | `synonymy_variant` | [decisions-proposed-synonymy.json](decisions-proposed-synonymy.json)、[gate-proposed-synonymy.json](gate-proposed-synonymy.json) |
| 附表 | `blocker_help` | [blocker-help.json](blocker-help.json)（每项未覆盖词元的候选承载 item） |
| 独立验证 | `verify` | [verification-v7-dryrun.json](verification-v7-dryrun.json)（形状往返 30 题 + P1—P16 探针 + 门） |
| 总表 | `main` | [dryrun-result.json](dryrun-result.json) |

复现：

```bash
cd /home/administrator/FrontierAgent
env -u PYTHONPATH uv run python \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-adoption-dryrun/run_adoption_dryrun.py
```

## 3. 关键数字

| 项 | 值 |
|---|---|
| 冻结槽位保留 | 23 条，逐字节一致 |
| 采纳新槽位 / 新条目 | 13 / 49 |
| 负例近似命中隔离 | 6 槽位 / 7 条目（不入映射池） |
| span 对账 | 全部通过（页号 + quote 逐字 + quote_sha256） |
| 重映射目标 | 82 = 必需 44 / 补充 20 / 待批准锚点 18 |
| 机器状态 | machine_ready 2 / pending_human 21 / blocked 1（`macro-004`）/ 负例 6 |
| 部分覆盖锚点 | 16（r25 为 13；增的是新条目带来的更细覆盖判定） |
| 裁决件 | 要件 40/40、整题验收 24、负例 6、状态澄清 1 |
| 门（机器口径） | `ready=false`，17 项要件未决 + 3 项人工同义映射 warning |
| 门（假设 U 逐项确认同义） | `ready=false`，仅 1 项未决（`industry-008-02`） |

## 4. 我做成了什么 / 我**没有**做什么

做成：

- 13 个新槽位 / 49 条条目按"采纳"口径转成版本候选，**只收支持证据**（被 `facet_reviews` /
  `question_reviews` 引用的 span），负例的近似命中/干扰项单独隔离成库文件；
- **署名口径（2026-09-18 更新）**：具名审核人 **xyl 已全文审核并确认署名**，`reviewer` 一律写 `xyl`，
  并用 `ai_assisted: true` 注明"AI 辅助核验（AI 复核者不是人类签名）"；提案原先把 `xyl` 预填在
  "待真人复核"的状态下（未签先行），本版补齐审核时间与 AI 辅助标记。追溯字段：
  `reviewer` / `reviewed_at` / `ai_assisted` / `ai_reviewer_label` / `adoption_ref`；
- 40 项要件全部机械映射到正式 schema（chosen 的 source 绑定、`anchor_review` 改选记录、
  `lexical_review` 只在可核验时写），24 整题验收 / 6 负例 / 1 状态澄清按采纳口径补齐；
- 门与阻断清单、以及"每项缺什么词元、哪个 item 含它"的补全建议。

没有做（有意）：

- **不自动扩 chosen**：没有把"恰好含缺词"的 item 自动塞进 chosen 来消 blocked——协议要求改选是显式
  人工行为并提交 `anchor_review`；本报告只给候选（`blocker-help.json`）。
- **不豁免事实**：`residual` 通道禁用；无法落位的词元一律留成阻断，不写成"同义即过"。
- **不冒签**：`reviewer` 记具名审核人 `xyl`（本人全文审核后确认署名），同时显式标注 AI 复核者不是
  人类签名（`ai_assisted: true`）；`macro-039-claim-001` 的历史"待真人复核"字样按"残留描述"处理，
  **不改写、不删除**历史字段。
- 不写正式 `decisions`/`approved`、不改冻结件、不跑 PG、不调模型、不读留出集。

## 5. 门为什么还没开

### 5.1 机器口径：17 项要件未决

判据是"chosen 的**引文**未覆盖该要件的判别性词元"。分两类：

- **改选即可（5 项）**：缺的词元在本题池内已有字面命中项（`blocker-help.json` 给了 slot#item_index）：
  `I32-company-004-02`（`实际`）、`I32-industry-002-02`（`格分`）、`I32-industry-003-01`（`2026`）、
  `I32-industry-008-01`（`32`）、`I32-macro-008-01`（`业样`）。
- **需逐词同义确认或补标注（12 项）**：`I32-company-001-01`、`I32-industry-001-01`、
  `I32-industry-002-01`、`I32-industry-006-01`、`I32-industry-006-03`、`I32-industry-008-02`、
  `I32-macro-001-01`、`I32-macro-003-01/02/03`、`I32-macro-004-02`、`I32-macro-006-01`
  ——多为"要求措辞 vs 原文措辞"（如"年度对应""区分附条件判断/市场预期/正式决定""供应链消息"）。

另 3 项已按人工同义映射接受但**挂 warning**（`macro-004-01`/`macro-004-03`/`macro-005-01`），
门把它记成"人工同义映射待审计（非机器语义证明）"。

### 5.2 对照口径（假设 U 逐项确认同义）：只剩 1 项

`I32-industry-008-02`（"须引用两份材料证明统计含义不同"）的 adopted chosen 里有一个
**纯日期 span**（`2026 年09 月06 日`）——机器拒绝把没有内容词元的 span 当成承载映射
（`content_units(span)` 为空即判无效）。处理办法只有两个：U 明确改选去掉/替换该锚点，
或该 facet 另定承载 item。**其余 16 项在对照口径下都能落位**（每个映射都记了
"本 span 未含下列词元的字面出处"并由具名人工承担同义判断）。

### 5.3 这不是"原文没有"

阻断全部是**映射与措辞层**的问题（要 U 逐项落位或改选），不是"原文缺事实"；
`macro-004` 仍是 `blocked`（题级），AI 已把四条路径 `K-path1..4` 逐页定位，但机器不能自行联合判完备。

### 5.4 上限口径：两项假设都成立时门能开

若 U 在 §5.2 的基础上也同意把 `industry-008-02` 的纯日期锚点改选掉：
**门 `ready=true`、0 阻断、20 条 warning（全部是"人工同义映射待审计"）**，
批准投影合计 `approved_required = 96` 条 / 30 题（跑在内存里，见
[gate-upperbound.json](gate-upperbound.json)，未写正式路径）。

⚠️ **96 条必需证据远多于冻结的 35 条**——这正是复核报告提醒的"不得把 85/96 条全变必需"。
本项目前把"facets 已批准的全部 chosen"一律投影成必需。若某 facet 的 chosen 是一组
（如 `industry-008-02` 的 5 条、`macro-004-03` 的四条路径），全变成必需会让 EvidencePass
要求"一条不缺"，与"多锚点联合满足同一要求"的语义不符。**需要 U 定口径**（见 §6.6）。


## 6. 转版时必须一并处理的事项（本轮已登记证据）

1. **署名**：`reviewer` 记为具名审核人 `xyl`（本人已全文审核并确认），并保留 `ai_assisted: true`
   与 `ai_reviewer_label`（AI 复核者不是人类签名）——`release-manifest.json` 的
   `reviewer_attribution` 记录了提案预填与本次确认的差异。
2. **结构性身份（Q3）**：采纳的 49 条**全是连续正文**，没有 `row/col/cell/unit/period`；
   表格类要求必须与冻结单元格**联合**取证（不能用正文条目替代行列身份）。`release-manifest.json`
   的 `structural_identity_gaps` 列了全部 56 条的位置。
3. **部分覆盖锚点 16 条**：审批时必须逐条落位（`adequacy=partial` 不允许直接批准）。
4. **候选文件哈希抖动**：候选 JSON 内含 `generated_at`，每次重跑哈希都会变；正式冻结前必须先固定
   产物再录哈希（冻结脚本的输入哈希检查会挡住过期审批件，但会浪费一次修订）。
5. **近似命中隔离**：负例的 7 条近似命中条目留在库文件里，**不得**被批准成必需证据。
7. **独立验证器 P5 期望值需随新版本更新**：`P5-supplementary-not-required` 把 company-005 的补充集
   写死成 `["company-024-claim-001"]`（r25 几何）；采纳补证后该题补充集变成 3 条（新槽位
   `company-ai-supplement-2026-09-06_dddc7cd0-p3` 贡献 2 条 + 原 1 条）。**这不是回归**，但新版本
   必须同步更新该期望值并写明理由（属版本化改动，不能静默改）。其余 15 个探针全过、
   自洽往返 **30/30**、验证器的门结论（false / 18 阻断）与本报告 §5.1 独立一致。
6. **必需/补充的口径（需 U 定）**：当前应用器把每个已批准 facet 的 `chosen` 全部投影成
   `approved_required`（上限口径下 96 条）。三种可选口径：
   （a）逐 facet 由 U 标"其中哪几条计入必需、其余作补充"（需要给裁决件加字段 → 新修订）；
   （b）按"每 facet 至少一组联合满足"建等价组，EvidencePass 只要求组内覆盖（同样需改协议）；
   （c）维持现状但**收窄 chosen**（每个 facet 只留最小充分集，其余进 `supplementary`）。
   本轮不改实现，先把数字与选项交给 U。

## 7. 事故与恢复记录（诚实登记）

第一次跑干跑时脚本用了 `runpy.run_path` 打路径补丁——**该 API 返回 globals 副本，补丁静默失效**，
生成器因此按冻结件跑到了**正式路径**，覆盖了 `i3-2/evidence-targets-candidates.json` 与
`evidence-targets-review.md`（生成器先自动归档，故原字节仍在）。

处理：用自动归档的 `-v6`/`-v3` 字节**按 r25 绑定哈希逐条核对后原样恢复**，删除多余归档，
`validate_i0c_freeze.py` **exit 0**；脚本改为 `importlib` 真模块加载 + `assert_patched()` 断言
（补丁没生效就拒绝运行）+ 跑完 `protected-artifacts-check.json` 复核 6 个受保护件字节未变。
教训已记入工作记忆。

## 8. 打开门的路径与之后的工程序列

U 的动作（二选一或组合）：

- **路径 A（省事）**：对 17 项逐项确认同义/改选（`blocker-help.json` 已给候选 item），并处理
  `industry-008-02` 的日期锚点 → 我据此生成正式 `decisions` → 门应开。
- **路径 B（严谨）**：那 12 项先补标注（新 source-gold 版本）再批准；`macro-004` 四路径改多锚点联合。

之后的工程序列（我做）：把 v4 版本候选与裁决件**落到正式路径** → 生成批准投影 + 门报告 →
**新建冻结修订（预计 r26）**绑定版本/候选/裁决件/投影/门/台账 → 回填 `docs/plan` 两份台账 →
`validate_i0c_freeze.py` exit 0 → 再谈 I3-2 其余冻结项（阈值/关键题/负例/旧基线映射）与 I3-1（E2E）→ M6。

**注意**：`ready=true` 之前不得宣称 I3-2 完成；本轮所有绿灯只证明契约与工程边界，
不证明 82 个候选已成完备金标，也不等于 U 逐页亲自核验。
