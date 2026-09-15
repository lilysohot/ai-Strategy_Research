# R2 语料证据流水线 · 指导解析

| 项 | 内容 |
|---|---|
| 版本 / 状态 | v1.0 · 2026-09-14（R2 执行态） |
| 用途 | 解释「原子分母 → 人工裁决 → 字段契约桥接 → 预算冻结」的语义、判据与边界 |
| 配套 | [流程总图](r2-corpus-evidence-pipeline-flow.md) |
| 事实真源 | [spec.md](../../.scratch/corpus-evidence-pipeline/spec.md)、[r2-p3s-report.md](../../.scratch/corpus-evidence-pipeline/r2-p3s-report.md)、[r2-p3h-report.md](../../.scratch/corpus-evidence-pipeline/r2-p3h-report.md)、[r2-p3i-report.md](../../.scratch/corpus-evidence-pipeline/r2-p3i-report.md) |

## 1. 这条链路是什么

R2 的目标不是"能调工具、能检索"，而是建立**有来源坐标、可核验、口径可比、可重算**的证据链。全链分两段：

1. **数据链（已闭合）**：源文件 → 保真解析 → 证据包 → 校验 → 版本化 → 投影/复算。
2. **验收链（R2 进行中）**：P3-R 提出最小节点 → P3-S 证明"机器范围没有切断目标" → P3-H 应用人工裁决 → P3-I 把批准分母投影到 P1 字段轴 → P4 冻结单轮预算。

核心原则：**机器可定位 ≠ 正确原子分母**。范围、子句格、覆盖率都是机器结构证明；"这条是否是一条完整、独立、可验证的研究 item"是产品语义判断，必须人工签核，且不可被自动替代。

## 2. 阶段速览

| 阶段 | 目的 | 关键产物 | 出口门禁 |
|---|---|---|---|
| P0 | 冻结基线 | 最小契约、联合金标 | 基线冻结 |
| P1 | 接口契约 | 字段轴（semantic_type / speaker_ref / value / unit …） | 契约冻结 |
| P2 | 技术门 | PG 只读核查、事故保留 | 技术门通过 |
| P3 | 固定开发回放 | planner 诊断 | 回放通过 |
| P3-R | 有限子句格 | 11,230 节点 / 3,327 边，35 个最小节点 | 结构门通过 |
| P3-S | 全文范围提供器 | 65 范围、35/35 目标唯一覆盖、17/17 正关系端点 | S0–S7（S6 人工） |
| P3-H | 人工裁决应用 | amendment overlay，30 旧批准继承 + 5 替代 item | H0–H5（H4 人工） |
| P3-I | 字段契约桥接 | 35 投影、8 speaker、8 value、49 unknown 约束 | I0–I6（I6 人工） |
| P4 | 预算批准 | 35 item · 5 调用 · 0 重试 单轮预算 | 反例通过后冻结 |

## 3. 关键概念与判据

### 3.1 原子分母（atomic denominator）
一条可独立记录、独立验证的事实 / 预测 / 观点，不含复合值。判定关注：**能否独立变化**、**验证路径是否不同**。判例：目标价（forecast，数值可验证）与评级（opinion，类别结论）可独立变化，必须拆成两条；"维持 26–28 年 EPS 预测值 67.74/70.77/73.84 元"虽无显式主语，但可由检索目标回推主体、且语料足够时，仍算完整可判定命题。

### 3.2 四项布尔检查（P3-S）
1. `one_research_statement`：是一条完整研究命题？
2. `necessary_condition_or_attribution_retained`：必要条件 / 否定 / 对象 / 时间 / 归属是否保留？
3. `no_unrelated_claim_merged`：是否混入无关命题？
4. `source_quote_and_locator_sufficient`：引文与定位是否充分？

### 3.3 四种裁决语义
- `approve`：四项全过。
- `needs_split`：检查 1/3 不过（仍混有多个独立命题）。
- `needs_merge`：检查 2 不过（缺条件 / 归属等必要成分）。
- `reject`：检查 4 不过（证据不足），或根本非研究 item（如寒暄、听音检查）。

### 3.4 字段契约桥接（P3-I）
把 35 条原子分母无损投影到 P1 字段轴，投影**只供 evaluator，禁止进模型 prompt（防金标泄漏）**：
- `speaker_ref`：`scope_id + speaker_role + identity_status` 生成，8 个去重 registry，可逆映射无碰撞。
- `value`：27 条保持 `unknown`；5 条为来源规范化字面；3 条仅允许命名白名单转换，不存在自由改写。
- `unit`：仅在源引文明确出现 `元` / `$` 时提出，否则 `unknown`，不猜测 shares / ratio / 评级单位。
- `unknown_fields`：49 个不确定性逐个映射为约束，无丢失、无去重冲突。

## 4. 人工复核指引

- **P3-S**：逐条对照源引文与最小节点，填四项检查 + 一种裁决 + 一段理由；另填审阅人、ISO 8601 时间、批准总数。校验器只查完整性与内部一致性（`approved_records` 必须等于 approve 数），不解释人工决定。
- **P3-I**：不需要重审 35 条原子性，只复核三件事：1 组全局规则、8 个 speaker 映射、8 条 value/unit（重点看 3 个白名单转换）。

## 5. 贯穿性约束

1. **零模型纪律**：P4 冻结前不跑模型；P3-I 即使被允许用模型也保持 0 调用——模型不能决定自己的验收标准。
2. **生产隔离**：scope-provider、bridge 均为 development-only；P2 保护清单（2336 个旧文件）不可被触碰。
3. **指纹绑定**：模板、评审文件、报告均以 SHA-256 固定；人工提交 SHA 与冻结基线必须一致，amendment 不改 base gold。
4. **失败即关门**：任何 split / merge / reject / needs_revision 都回 development 零模型修订，不删除失败样本，不伪造结果。

## 6. 当前状态与下一步

- 已通过：P3-S 结构门、P3-H（35 条全部人工批准，5/5 替代项）、P3-I 零模型投影门（I0–I5）。
- 待办：完成 P3-I 人工桥接签核并校验 → 实现并反例验证 P4 scratch runtime / scorer 对 3 条 transform、speaker registry、unknown constraints 的执行语义 → 冻结 runner / scorer / prompt / model / config 的单轮预算（35 item · 5 调用 · 0 重试）→ P4 模型输出的 text/constraints 忠实度结果后人工裁决。
