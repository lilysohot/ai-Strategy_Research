# I3-2 采纳稿落地记录（2026-09-18，i0c-r26）

> 本文件是**落地记录**（未纳入 r26 绑定，属补充审计证据）。本目录其余文件是**采纳前的干跑产物**，
> 其中 [report.md](report.md) 描述的是"未写正式路径"的干跑状态——落地结果以本文件与
> `freezes/i0c-r26.json` 为准。

## 1. U 的裁决（全部按建议）

| 决定 | 取值 | 落地表现 |
|---|---|---|
| 1 那 17 项怎么处理 | **A**：AI 核验锚点逐项确认同义 | 裁决件含 20 条 `lexical_review`；门记 20 条 warning「人工同义映射待审计（非机器语义证明）」；署名 `xyl` + `ai_assisted: true` |
| 2 `industry-008-02` 纯日期锚点 | **去掉** | 该 span（`2026 年09 月06 日`）记入 `supporting_anchors`（理由：无内容词元，不能作承载映射） |
| 3 必需/补充口径 | **(c) 收窄 chosen** | chosen 53 → **35**；移出的 **18** 条记 `supporting_anchors`（不计入 EvidencePass）；批准投影 = 必需 **79** + 补充 **20** |
| 4 `macro-004` 题级 blocked | **先补四路径联合锚点** | q1/q2 承载 `…cc03f55b-p1#1`（"我们本篇报告关注前面四个主体"）、q3 四路径 = `p1#2`+`p1#3`+`p1#4`+`p2#0`；机器 `blocked` 原样保留并加 `machine_status_override` 说明 |

## 2. 落地动作与结果

| 步骤 | 结果 |
|---|---|
| 归档 r25 绑定字节 | `before-r26/.scratch/.../source-gold-frozen.jsonl`（sha `c360a132…`，作为 r26 的 `i3_2_archive` 条目） |
| 装新金标 | `source-gold-frozen.jsonl` `c360a132…` → **`37662c77…`**（36 槽位 = 冻结 23 条逐字节保留 + 采纳 13 槽）；负例库 `i3-2/source-gold-nearmiss-library.jsonl` |
| 重跑生成器（mapping-6） | 候选 **v7** `7d4a1c76…`：30 题 / 目标 **82**（必需 44／补充 20／锚点 18）/ `blocked` 1 / 负例 6；被覆盖字节归档 `-v6` |
| 落裁决件 | `i3-2/evidence-targets-decisions.json` `09ed8429…`（40 要件 + 24 整题 + 6 负例 + 1 澄清；`reviewer=xyl`，`ai_assisted=true`） |
| 跑门 + 批准投影 | `approval-report.json` `8dd239bf…` **ready=true／0 阻断／20 warning**；`evidence-targets-approved.json` `5b89d981…`（79 必需 + 20 补充） |
| 版本化修正 P5 期望值 + 跑验证 | `i3s2_verify_candidates.py` `4e85ca41…`；`evidence-targets-verification.json` `8ac7dd60…`：自洽 **30/30**、探针 **16/16**、门 true |
| 台账回填 | `docs/plan/corpus-ingestion-rebuild-tasks.md`、`docs/plan/claims-market-closed-loop-plan.md`（I3-2 行 + 当前状态段；r25 段落标为历史） |
| 冻结修订 | `freezes/i0c-r26.json` `7577ba2d…`（parent i0c-r25；7 组绑定：tooling 4／source_gold 2／assets 8／archive 6／regressions 21／docs 2／validator 1） |
| 验证 | `validate_i0c_freeze.py` **exit 0**（含新增 r26 规则：金标首次直接入链、归档完整性、越界组检查） |

**未改**：`query-gold-frozen.jsonl`（`6f6c5a25…`）、`guards/i3.json`、`plugins/`、`tests/`、数据库与模型
（零模型、零 PG 写入、未读候选业务结果）。

## 3. 仍待办（不得据此宣告 I3-2 完成）

1. **20 条人工同义映射待审计**：机器只核 span 出处；若要"机器可证的语义等价"需另设抽样复核。
2. **`macro-004` 的机器 `blocked` 未消**：q2 靠人工裁定承载；建议下一版映射规则（mapping-7）覆盖
   "短句由相邻段落承载"这类情形，否则每版都要人工越权。
3. **I3-2 其余冻结项**：阈值／关键题／负例／旧基线映射未纳入本轮。
4. **I3-1（E2E）**：待 I3-2 收口后解冻（需 PG/模型与预算授权）。
5. **I3-5**：真实生成答案语义验收仍未执行（门只核登记/投影保真）。
