# B2 金标无关拒检探针 — 执行阻塞报告（2026-09-21，只读）

## 一、结论

**探针脚本已就绪（`probe.py`），但当前无法运行：测量语料（index-4-zhcfg-2，8 份 active builds）
已不在沙箱库中，`i2_sandbox_corpus` 只剩 1 个测试残留 build。**

## 二、证据（本次实跑）

```
$ uv run python .../20260921-f1-goldfree-probe/probe.py --no-write
RuntimeError: Active corpus has 1 sources (expected 8)      # 脚本自带 8 源守卫，逻辑接线正确

$ 直查沙箱库（postgresql://postgres:postgres@127.0.0.1:543/i2_sandbox_corpus）
corpus.corpus_publications = 1（active 1）
  source_id    = cbf58d57…（1 份）
  active_build = ccededc2…
corpus.corpus_builds = 1

$ 端口/库普查
port 543  databases: i0b2_verify_apodex / i0b2_verify_postgres / i2_sandbox_corpus / postgres
          i2_sandbox_corpus: publications=1 active=1 builds=1   ← 唯一含 corpus schema 的库
port 5432 databases: apodex / postgres（均无 corpus schema）

$ 仓库内是否存在 8-build 备份
find . -name "*.dump|*.sql|*backup*" → 仅
  audits/20260922-r4s-rebind/before-r4s/backup/corpus_tables_backup.txt（**本身就是 1-build 状态**：
  corpus_admissions rows=1、decision_id='d1'）
  backups/i0b1-20260915T0714Z/pg/*.dump（I0B-1 时点，非 I3 语料）
```

**消失时点（机读推断）**：F2 的 `fetch-receipts.json` 记录了当时 8 个 build id
（`e3820ab3…/58735cff…/6475cbac…/6b55ddbb…/1227c2a3…/a3b681fd…/7734638e…/99bf1ba2…`）；
F4 回放（18/24）仍看到 8 源；r4s 在 2026-09-21 19:27 取的"pre-r4s 备份"已是 1-build 状态
⇒ 语料是在 **F4 回放之后、r4s 之前**被清掉的，与 M5 复核矩阵的"U 授权清库"（`audits/20260922-m5-rereview/consumers-clean/`）
时点吻合，清库后**没有恢复步骤**。

## 三、影响（超出 B2 的新发现，记 B8）

1. **F2 的 18/24、F4 的 18/24、funnel `S1=66 / S2=60 / S4=50`、F1/F2 的"负例 6→0"认证读数，目前均不可复现。**
2. 任何后续「方案后同口径对比」在恢复语料前都无法执行（spec §13.4 的对比纪律要求同一 active corpus）。
3. F3（clean 句粒度）的重摄入被**双重阻塞**：既未授权写库，语料本身也不在。

## 四、解阻塞方案（需 U 授权）

| 方案 | 内容 | 成本/风险 |
|---|---|---|
| **A（推荐）** | 全量重建沙箱语料：`corpus plan`（8 份来源 + i31 裁决件）→ `build` → `publish`（沙箱 DSN + `guards/i3-e2e.json`，无模型调用；发布集按 i0c-r37 具名签认：7 份发布、光力 `dddc7cd0` 维持不发布） | 一次全量重摄入（PG 写，仅 `i2_sandbox_corpus`）；**顺带让 F3 的 clean 句粒度语义生效**（B3 一并解） |
| B | 从外部/其他机器恢复 8-build 语料快照 | 仓库内已确认无此类备份；若 U 手上有则最快 |
| C | 不恢复 ⇒ 探针与所有同口径对比继续挂起 | F1/F2/F3/F4 的读数长期不可复现 |

**口径提醒（重要）**：重建后**不得**把新读数与历史 18/24 相减（语料已按 F3 语义重建，是不同字节）。
探针自带 `off` 变体复现基线，**同一次运行内的 a1/a2/a3 vs off 对比**即为合法对比（同语料、同 session、
同 scorer 字节），不需要跨语料历史数字。

## 五、探针已就绪的设计（等语料即可跑）

- 30 题一律同路径：OR 查询 → `search_with_coverage_bands` → `select_band` → `fetch_bands` →
  `_assemble_band_documents`（产品 band_s2 路径，含 cell 投影）；**不按 `answer_existence` 分支**。
- 变体：`off`（基线）/ `a1_unit`（单元级全内容词元）/ `a2_item`（带内块级）/ `a3_doc`（文档级）。
- 判据：I-M6-1 负例全 0；I-M6-2 有答案题 S1/S2/S4 与 band_s2 EvidencePass 不回退；I-M6-3 谓词金标无关
  （静态断言 + 30/30 题一律施门）；附加"被丢弃文档点名"作为召回损失证据。
- 产物 write-once：`probe-summary.json` / `probe-trace.json` / `probe-dropped-docs.json` /
  `probe-funnel-targets.json` / `probe-report.md` / 各变体评分文本。

## 六、纪律
本报告为只读核查产物；未写库、未重摄入、未 commit、未改任何冻结字节。
