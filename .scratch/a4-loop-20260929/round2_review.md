# A4 修复后复核（Round 2，2026-09-29）

背景：F2（发布边界对被取代候选求并集）修复后（同拥有者取代 + 清单写入 `owner_role`），
用与 Round 1 完全相同的方式重跑 `company-003` 三档，复核修复是否在真实运行中成立、
闭环是否仍工作。命令：

```bash
uv run python .scratch/a4-loop-20260929/a4_loop_probe.py --query-ids company-003 --tag r2
uv run python .scratch/a4-loop-20260929/a4_loop_probe.py --query-ids company-003 --guided --tag r2-guided
uv run python .scratch/a4-loop-20260929/a4_loop_probe.py --query-ids company-003 --early --tag r2-early
```

## 1. 结果

| 档 | 提交次数 | 候选清单 owner | 环内闭环 | 环内终态 | **发布边界** | 边界 counts |
|---|---|---|---|---|---|---|
| 自然（r2） | **8** | 8 份全部 `stateful_react:1fb465cb108c` | 否（8 次同一 `missing_dependencies` 未修） | `partial` | `partial` | supported 4／partial 1 |
| 引导（r2-guided） | **0** | 无 | 未触发 | — | `draft` | — |
| 早提交（r2-early） | **2** | 2 份全部 `stateful_react:3d9246152ab9` | **是** | `verified` | **`verified`** | supported 2／partial 0 |

run：`20260929-144201+0800-react-5233`（自然，墙钟 1240.7s）、
`20260929-150241+0800-react-eac1`（引导，529.3s）、`20260929-151131+0800-react-2896`（早提交，613.1s）。

## 2. 结论

### 2.1 F2 修复在真实运行中确认
- **每份候选清单都带同一 `owner_role`**（自然 8/8、早提交 2/2；引导无提交）。owner 取
  `ExecutionScope.task_id`，同一代理跨多次提交不变。
- **边界只计最新提交**：自然档 8 份候选共 40 条结论，边界 counts 恰为最新一份的
  `supported 4／partial 1`（5 条），**不是并集**。修复前同场景会是 40 条并集、几乎全 partial。
- 早提交档边界 **`verified`**（修复前同路径为 `partial`）。

### 2.2 边界现在是「最新提交」的忠实反映
自然档边界判 `partial` **不再是污染**，而是模型确实声明了 `required_dependencies: value`
却未提供对应 purpose 的证据（`missing_dependencies`）；工具返回的提示逐条给出，模型 8 次
都没改。**这是诚实信号**，正是 F2 修复要达到的效果。

### 2.3 新发现 F4：模型行为方差大，闭环不保证收敛／不保证合规
- **不合规**：引导档加了「必须登记并按反馈重提」的显式要求，本轮模型**一次都没提交**
  （0 次）→ 边界 `draft`。合规不是确定性的。
- **不收敛（thrashing）**：自然档模型自发提交 **8 次**、耗时 1240.7s、输入 1.45M token，
  同一条 `missing_dependencies` 始终未修 → 反复重提但无进展，成本显著放大。
- 对**「是否默认启用阻断」**的直接影响：若开启 `A4_ENFORCE`，本轮三档会有 **2/3 被降级**
  ——一次因为模型**根本没提交**（`draft`），一次因为它**确实没满足自报依赖**（`partial`）。
  前者是合规问题、后者是证据问题，两者都在「模型行为」层面，不是校验机制缺陷。

## 3. Round 1（修复前）vs Round 2（修复后）

| 档 | R1 提交 | R1 边界 | R2 提交 | R2 边界 |
|---|---|---|---|---|
| 自然 | 1 | `partial`（4×`not_in_report`，并集污染） | 8 | `partial`（1×`missing_dependencies`，最新提交，**无污染**） |
| 引导 | 2 | `partial`（并集污染） | **0** | `draft` |
| 早提交 | 2 | `partial`（并集污染） | 2 | **`verified`** |

## 4. 复现

产物：`model_runs/{r2,r2-guided,r2-early}/company-003/result.json`、
`a4_loop_probe.{r2,r2-guided,r2-early}.json`；run 工件在 `.apodex/runs/<session-id>/corpus/`。
零模型对照见 [`replay_f2_fix.py`](./replay_f2_fix.py)。
