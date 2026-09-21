# 检索解耦方案（spec.md）闭环性复核 — 审计报告

- 生成：2026-09-21；类型：**只读复核**（未改代码、未改冻结链、未改金标）
- 复核对象：`.scratch/corpus-retrieval-decoupling/spec.md` + `issues/00`–`09`
- 独立性偏差登记：本复核在同一工作树内执行，且与 spec 的撰写/实施为**同一类会话链**（无全新独立会话）。
  按约定，本报告的"未闭环"结论**不构成放行签认**，放行仍需独立复核 + U 具名签认。
- 结论一句话：**票 00–05（解耦主线）闭环；F1–F4 中 F2/F4 闭环、F3 半闭环、F1 未闭环；i1 冻结门转红为新引入阻断；M6 未闭环。**

---

## 一、实跑命令与结果（本次复核留证）

| # | 命令 | 结果 | 判定 |
|---|---|---|---|
| 1 | `uv run python ...freezes/validate_i0c_freeze.py` | `i0c_EXIT=0`（末行 `i0c freeze chain verified`，含 r4s 段） | ✅ 绿 |
| 2 | `uv run python ...freezes/validate_i1_freeze.py` | `i1_EXIT=1`；`FREEZE CHECK FAILED: r5.binding[tests]: tests/test_corpus_preparation_admission.py 哈希失配或缺失` | ❌ **红** |
| 3 | `uv run python ...freezes/validate_i3_2_completion.py` | `i3_2_EXIT=0`，`i3_2_complete: true` | ✅ 绿 |
| 4 | `uv run pytest tests/test_corpus_*.py -q` | `751 passed, 12 skipped in 44.58s` | ✅ 绿 |
| 5 | 沙箱 PG 连通性 | `DB OK ('i2_sandbox_corpus',)`（`psycopg` 需在 `uv run` 下） | ✅ 可用 |

> 注：shell 里 `cmd | tail; echo $?` 取到的是 `tail` 的退出码 —— 本次改为重定向到日志后取 `$?`，与 spec §"假绿陷阱"一致。

---

## 二、闭环判定（逐项）

### A. 已闭环（有盘上证据 + 门绿）

| 项 | 证据 | 本次复核 |
|---|---|---|
| 票 00（S1 清账） | `i0c-r42`：t6 重绑 + `scoring-input-manifest.json` 血缘重建 | i0c 门绿，r42 段在验证器输出中 |
| 票 01 选择策略落产品 | `selection.py`（`select`/`select_structural`），r43 接入生产 | i0c 门绿（r43 段：tests 731 passed） |
| 票 02 SearchHit 加深 | `search_pg.py:94/105`（`label_path`/`_enrich_hits`） | 同上 |
| 票 03 | 归属裁决选 A，**作废**（band 承载连续区间） | issues/03 标 completed(作废) |
| 票 04 表格结构下沉 reader | `pdf_reader.py:146/519-533`、`contract.py:309` | 同上 |
| 票 05 清洗判定机读 | `NoiseVerdict`/`CleanRegion.verdicts` + I-E1/E2 常驻测试 | 回归 751 含之 |
| F2（band 接生产 + cell） | `i0c-r4n`；`service._selected_chunk_hits`（service.py:1012）docstring 明示"生产默认：band"，`search_bands` 接线 `cross_boundary.aggregate_band_chunks`（service.py:968/982）；`f2-summary.json` 18/24 | 代码实测存在，与 spec 一致 |
| F4（跨 NOISE/kept 边界取证） | `i0c-r4q`；`cross_boundary.py` 首入链；I-ATT-1 3 条测试；`tests/test_corpus_selection.py` 30 passed | 回归 751（748+3） |
| r4r / r4s 记账修订 | r39 校准漂移豁免；M5 两处 MISS 修复（consumers `sel-d{i}`、dev-lane 拆文件） | i0c 门绿（r4s 段：consumers-pg 20 passed） |

### B. 未闭环（7 项）

**B1｜i1 冻结门转红（本次实测，spec 未登记）** —— 最高优先级
- 现象：`validate_i1_freeze.py` exit 1，`r5.binding[tests]: tests/test_corpus_preparation_admission.py 哈希失配`。
- 机读归因：i1-r5 绑定该文件 = `ccfd2dd8...`；r4s 为修复 M5 MISS ② 删除 dev-lane 块，当前文件 = `6adbb274...`
  （`sha256sum` 实测）。i0c-r4s 已重绑（grep 命中 `6adbb274`），**i1-r5 未同步** ⇒ i1 链红。
- 影响：spec §"M5 F3＝i1-r5"段声称"三验证器 exit 0"，以及 §"M5 复核矩阵"声称"三冻结链 exit 0"，**均已不成立**。
- 修法（须 U 门控，不代做）：新建 `i1-r6`（archive-first 归档 i1-r5 字节）重绑该测试 + 验证器；或在 i1 校验器加 supersession 豁免
  （r4s 已改该测试的既成事实，与 r4r 对 r39 的处理同型）。

**B2｜F1（负例 6→0）未闭环 —— 且方法口径需 U 裁决**
- 产品侧无接线：`grep -rn "negative_query" plugins/` **零命中**（除模块自身不引用），`service.py` 无 `no_answer`/`abstain`
  处理（`grep "no_answer\|abstain" plugins/corpus/service.py` 零命中）⇒ 生产路径对 no-answer 题仍走 OR 宽召回。
- 未入冻结链：`grep -rln "preparation/negative_query.py" freezes/` 零命中；`tests/test_corpus_negative_query.py` 亦未绑入任何修订。
- 6→0 的来源：F2 的 `f2-summary.json.negative.certified_retrieved_documents_0` 全 0，是 **`f2_backtest.py:261` 在回测脚本里
  `import negative_query`** 得到的；同一文件 `or_canary_retrieved_documents` 仍为每题 5 ⇒ 证明"未收紧就是 5"。
- **口径冲突（须裁决）**：`f1_backtest.py:98/147` 以金标 `q.answer_existence is AnswerExistence.NO_ANSWER` 为分支条件才收紧查询，
  与 spec §11「**不按金标**词/页/行列补取证据（评测量尺不得来自金标）」直接冲突；也与 spec §6.0"修它需要动'何时判定无答案'
  （相关性阈值/AND 语义/abstain 通道）"的原判断一致 —— 现在是"知道无答案才收紧"，不是"判定出无答案"。
- ⇒ 结论：**M6「已知伪引用负例为 0」在产品侧仍为 6**，F1 只证明了"收紧查询可到 0"。要么产品加真实 abstain/拒检通道（真改产品行为），
  要么该 6→0 不能计为 M6 判据达成。

**B3｜F3 半闭环（代码闭环，语料未应用）**
- `clean.py` 句粒度改动已冻结（r4p，`d46491b2`），I-E3 常驻测试在回归内。
- 但改 kept ⇒ 须重摄入；r4p 自述"PG 写库未授权，另立作业承接" ⇒ **company-007/e1 在当前语料仍未转绿**，F3 的目标级验收未达成。
- 附带：`audits/20260921-f3-disclaimer-granularity/` **只有 `before-r4p/` 归档三个文件**，spec §14.5 声称的"整库 8 build 回放"
  机读复核产物（报告/回放输出）**不在盘**，`grep -rl "_has_numeric_fact_sentence" audits/` 亦零命中 ⇒ 该结论目前**无落盘证据**。

**B4｜company-003（光力科技）独立议题未立项**
- spec §10.2 明确"须单独立题"（band/cell 均不能修，属文档级召回），`issues/` 仅 00–09，`company-003` 只在 `07` 里被提及。
- 影响：19/24 封口、以及 6 个 company-003 cell 目标，全部挂在这个未立项议题上。

**B5｜M6 未闭环（spec §6.0 对账表仍然成立）**
- EvidencePass 生产 **18/24** vs 冻结门槛 **23/24**；关键引用题 100% 未达；
  旧检索/财务基线非回归**未验**；I3-7 对 I3-6 重验**未开始**（I3-6 未定版）。
- 只有"格式覆盖 PDF/DOCX/MD"一项为 ✅。⇒ 本方案（解耦 + F1–F4）不等于 M6 放行。

**B6｜M5 复核未签认**：spec 自述"M5 结论仍待独立复核 + U 签认"；且 M5 复核矩阵中"三冻结链 exit 0"因 B1 已失效，重跑前不能引用。

**B7｜工作树未收口**：`spec.md` 修改未提交、`audits/20260921-f1-negative/f1_replay_readonly.py` **未跟踪（未归档）**、
`MEMORY.md` 修改未提交 ⇒ 证据链有未落盘/未提交部分。

---

## 三、建议的最小收口顺序（待 U 裁决后执行）

1. **B1（i1 门红）**：新建 `i1-r6` 重绑 admission 测试 + 验证器（archive-first），恢复三门全绿 —— 记账类，无能力收益，建议与下一笔能力改动合并。
2. **B2 裁决前置**：U 定"F1 的 6→0 算不算 M6 达成"。若算 ⇒ 必须在产品侧加 abstain/拒检通道并把 `negative_query.py` + 测试入链；
   若不算 ⇒ F1 降级为"可行性证据"，负例仍是 M6 唯一硬阻断，须按 §6.0 重新立项。
3. **B4**：补立 company-003 独立议题（文档级召回）。
4. **B3**：F3 重摄入作业（需 PG 写授权）+ 补落盘 f3 回放证据。
5. **B5/B6**：M6 与 M5 放行走独立复核 + U 具名签认，实施方不自宣。

## 四、纪律声明
本报告为复核文本，**不是交付物**；未改任何实现/测试/金标/冻结链字节，未 commit、未 publish、未重摄入。
