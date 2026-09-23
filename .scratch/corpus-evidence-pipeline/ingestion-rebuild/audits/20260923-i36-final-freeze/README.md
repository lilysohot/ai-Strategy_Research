# I3-6 最终冻结（结束校准 + 不可变最终 manifest + M4/M5 重验核定）

- 日期：2026-09-23；零模型；零写库；留出零读取；git 零操作
- 产物：[i3-final-freeze-manifest.json](../../i3-final-freeze-manifest.json)（写盘后 sha256 `4152179ffeed…`，
  write-once，重跑语义逐字段一致）
- 依据：任务清单 §3.6 I3-6 行（前置 I3-3/I3-4/I3-5 均已收口：I3-1 i0c-r38、I3-2 r31、
  I3-3 校准 + r40—r4x 修复簇 + b5 盘点、I3-4 coverage 族、I3-5 audits/20260923-i35-legacy-nonregress）

## 冻结内容

1. **冻结版本定义**：i0c 冻结链链头 **i0c-r4z**（sha256 c0950bf76d06…，parent=i0c-r4y）。
   版本的有效绑定集合以 `validate_i0c_freeze.py`（当前 sha 817b7779…）核验的
   i0c-current + i1 链为准；manifest 是版本索引与核定记录，不复制绑定（架构 §12.1）。
   三门验证器在本轮开工前基线核验全部 exit 0（r29 NOTE 为既有非失败项）。
2. **关键资产显式哈希**（28 实现文件 + 4 规则/配置 + 5 预期/policy + 9 守卫 +
   4 基础设施/重建路径 + 12 测试锚点）：scoring.py `f61573d7…`（r41 冻结评分器，未漂移）、
   calibration-plan-v2.json `b82c8d94…`（min_rate=19/20）、query/source-gold-frozen、
   baseline-bindings、guards 九件、sandbox_schema.sql 等。
3. **运行时配置**：REV 常量（reader-pdf-6 / reader-docx-2 / reader-md-2 / clean-3 /
   chunk-3 / index-4-zhcfg-2 / ingest-1 / admission-probe-1）；开关默认值
   （RANK_LEXEME_PRUNE=on [r4v/r4w]、stitch_continuation=on [r4u]、
   attach_source_note=on [r4y]、CORPUS_ABSTAIN_NO_ANSWER 代码默认 off / M6 评测口径 on
   [r4t + I-M6-1]、CORPUS_READ_CHAIN=auto、CORPUS_DEV_LANE 仅 dev lane 装载）。
4. **校准收口声明**：I3-3 按 r39 预定两轮停止后，经 r40—r4x 修复簇与 b5 盘点收敛——
   三类 DocRecall=100%、QuestionPass=24/24、EvidencePass=24/24、关键题 22/22、
   评分层 FP=0、产品层 abstain 6/6（audits/20260923-b5-final/b5-inventory.json）。

## 核定需重验的 M4/M5 门（→ I3-7 清单）

manifest `m4_m5_gates_to_reverify` 九组：I2 全链路 12 项（test_fullchain_probes.py
write-once 不修改）、缺口处置契约、M4 内存链 corpus 家族（plain + i1 守卫 env）、
M5 PG 门族（i2-verify 守卫 env + CORPUS_I2_DSN→重建沙箱，核心门零 skip）、
dev lane 门（i3-e2e 守卫）、legacy 非回归（旧库 5432 只读：golden 19 + 财务 47 +
公式 7 + 负控 + 客户表 12 + 正文 2 + 宏观 0/3 单列 + 审批契约门 32）、
负例双口径（评分层 FP=0 + 产品层 abstain=on 6/6）、静态门（ruff/pyright/import_smoke）。

## 待定项核定（无一为冻结必需待定项）

| 项 | 状态 | 性质 |
|---|---|---|
| prose_numbers 重抽取（4 次模型调用） | not_run_pending_budget | r27 另立预算授权 |
| 真实答案语义测试 | not_run_pending_authorization | 任务行另定输入/判据/预算 |
| guosen_maotai 留出 10 格 + customer 原文 re-parse | held_out_guard_protected | 守卫 forbidden_roots；独立留出另验须 U 显式解锁 |
| 宏观旧规范字段 0/3 | preserved_failure | 失败基线保留单列，非待定项 |

## 放行声明

本 manifest 仅冻结版本；**M6 不在本轮放行**——须 I3-7 对本冻结版本全链重验通过且
全部结果与版本一致，再经独立复核 + U 具名签认。I3-6 后任何影响运行的变化将使
最终报告失效，回到新的版本冻结与 I3-7（任务清单 §3.6 尾注）。

## 链上收口

tasks.md §0/I3-6 回填 → 冻结修订 **i0c-r5a**（parent=i0c-r4z；archive-first 归档
tasks.md 改前字节 == r4z 绑定 aef577bd…、验证器改块前字节 == r4z 绑定 817b7779…；
验证器追加 r5a 语义门块）→ 三门验证器 exit 0。

## 纪律核对

触及字节 = 本审计目录 + i3-final-freeze-manifest.json（新产物）+ tasks.md 回填
（经 i0c-r5a 入链重绑）+ 冻结链文件（i0c-r5a.json / freeze-manifest.json /
validate_i0c_freeze.py）。零模型、零写库（5432/543 均只读未触碰）、留出零读取、
不 commit / 不 publish / 不重摄入。
