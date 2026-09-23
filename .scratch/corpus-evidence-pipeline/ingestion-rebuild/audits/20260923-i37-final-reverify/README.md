# I3-7 最终重验（I3-6 冻结版本重建/索引 + 评分/取证/负例 + 测试电池 + legacy 非回归）

- 日期：2026-09-23；零模型；隔离 PG（沙箱 127.0.0.1:543/i2_sandbox_corpus + 临时第三库 i2_d2d6_corpus）；
  生产库 5432 零触碰；留出零读取；git 零操作
- 冻结版本：i0c 链头 **i0c-r4z**（绑定链修订 i0c-r5a；manifest sha `4152179ffeed…`）
- 三步产物（均 write-once）：[rebuild-report.json](rebuild-report.json)（重建步）、
  [i37-score-results.json](i37-score-results.json)（评分/取证/负例）、
  [i37-tests-results.json](i37-tests-results.json)（测试电池）、
  [i37-legacy-results.json](i37-legacy-results.json)（legacy 非回归）

## 重建步（用 I3-6 冻结版本重新构建/索引）

[i37_rebuild.py](i37_rebuild.py)：teardown → apply（fail-closed 目标校验）→ 播种 8 份审查决定
（decision_id 与 dev-scope-manifest.json 逐字一致；U 2026-09-20 裁决同款路径）→ build/check/publish
→ gap-review 复用 i42 签署件。结果 **8/8 published+active**，index_rev `index-4-zhcfg-2`、
chunk/parse/clean revs 与 b1 冻结报告逐一复现（重建确定性）。守卫 `guards/i3-e2e.json`；
dev lane 两份 dev 来源按 `CORPUS_DEV_LANE=1` 装载。

## 评分/取证/负例电池（14/14 门全绿）

[i37_score.py](i37_score.py) 对重建沙箱 active 语料（新读链）重跑三类 30 题：

- **QuestionPass 24/24、EvidencePass 24/24、三类 DocRecall=1**（company/industry/macro 各 8/8）；
- **关键题 22/22 全过**；评分层 **FP=0、伪引用=0**；与 b5 盘点基线对照**零回退**；
- `RANK_LEXEME_PRUNE` on/off 对照：on 无劣化（1 题更优、0 回退）；
- 负例双口径：评分层无 FP；产品层 `CORPUS_ABSTAIN_NO_ANSWER=on` **负例 6/6 拒答**（冻结口径仅断言此项）；
- authority/取证：句柄格式、locator 回环（build_id/chunk_id 匹配、文本非空）、未知句柄拒绝，全过；
- 冻结 policy（min_rate=19/20、top_k=5、critical 全过、FP=0）与 manifest 逐字段一致。

**Pending 登记（非 I3-7 门，待 U 裁决）**：abstain=on 下 **24/24 正例被拒检**——AND 预检要求
单个单元同时含全部实质词元，真实语料归零（band 检索靠 OR+带聚合仍命中，正例分数不受影响）。
「正例不误拒」（S1）设计宣称未获正例证据；不擅改冻结代码，登记 pending。

## 测试电池（9 门全绿）

[run_tests.py](run_tests.py)：7 lanes + 自愈前置 + 恢复终检，9 门全绿、`passed=true`：

| lane | 守卫 env | 结果 |
|---|---|---|
| m4-plain | 无（plain env，内存链） | 320 passed / 0 failed / 7 skipped（PG 用例无 DSN 自然 skip） |
| m4-i1 | guards/i1.json | 320 / 0 / 7（同上） |
| dev-lane | guards/i3-e2e.json | 9 / 0 / 0 |
| m5-search-live（首跑） | i2-verify + CORPUS_I2_DSN | 11 / 0 / 0（`_live` 门在真实 8 源完好时跑） |
| fullchain-12 | i2-verify + CORPUS_I2_DSN | 12 / 0 / 0（write-once 不修改） |
| m5-hermetic | i2-verify + CORPUS_I2_DSN | 74 / 0 / 0（7 文件逐用例 TRUNCATE 自含） |
| m5-dsn-d2d6 | **无守卫**（偏差 lane，见下） | 73 / 0 / 0 |

恢复终检：lane 后 drop 第三库 → `--restore` 子进程复跑重建流水线 → 8 源 build_id 与
rebuild-report 逐一复现、active 指针严格等于 8 源集合（测试残留清零）。电池启动另有自愈前置
（清残留第三库 + 预恢复，防上轮中途崩溃留下无 schema 中间态）。

### lane 设计的关键约束（实测发现）

- **M5 PG 各文件逐用例 TRUNCATE 全 corpus schema**（I2 时代自含沙箱设计），而 search_pg 的
  `_live` 门需要既有语料多命中（`POOL_QUERY` OR 串 >1 命中）——故 search_pg 必须最先跑，
  全部破坏性 lane 排后并以重建收尾。
- **守卫 Popen 注入**：`guard.install()` 会包装 `subprocess.Popen.__init__`，向 Python 子进程
  注入父进程守卫引导；子进程再按 env 换装即被拒（fail-closed）。推论：**父 runner 不得装守卫**
  （各 lane 子进程经 env 自声明），**恢复步（需装 i3-e2e）必须经 `--restore` 独立子进程执行**
  ——两轮实测复发（换装被拒 + `CORPUS_DSN` 被投毒成哨兵）后确立。属冻结守卫的正确 fail-closed
  行为与运行纪律约束，非产品缺陷。

### D2/D6 偏差登记（双重偏差，均 fail-closed 语义正确）

1. claims/metadata 的 PG 用例走 `service.dsn()`（优先级 1 读 `CORPUS_DSN`），而 corpus 守卫对
   `CORPUS_DSN` fail-closed 投毒 → 守卫 lane 下必 skip（实测 21 skip 即此来源）→ 本 lane **无守卫**
   运行；零模型由测试假实现注入保证。
2. D2/D6 为 legacy 形态用例（直插临时 schema 的 documents/blocks + legacy 句柄 fetch），设计前提
   = 目标库**无 corpus schema**（auto 探测判 legacy）。沙箱含 corpus schema 时双向 fail-closed
   （auto → `LegacyHandleError`；强设 `CORPUS_READ_CHAIN=legacy` → `StoreError` 拒绝新库静默降级，
   两轮实测均拒，冻结行为正确）。解法：隔离 543 容器内新建**无 corpus schema 的第三库
   `i2_d2d6_corpus`**（`CORPUS_DSN` → 第三库、`CORPUS_I2_DSN` → 沙箱；生产库与沙箱零影响）；
   恢复步前 DROP（`i2s1_apply._check_target_instance` 对实例库集合 fail-closed，冻结资产不可扩）。

## legacy 非回归复验（i37_legacy.py，判定逻辑与 I3-5 逐字同口径）

财务 47/47（tolerance=0）+ 公式 7/7 + 高盛负控 PASS；客户表 12/12；正文冻结 2 例 2/2；
宏观 0/3 失败基线保留单列；旧检索 golden **19/19**（O6 按 r27 排除）；审批/投影契约门 PASS。
golden 逐题结果单列。总门 `financial_formula_negative_customer_macro_gate=true`。

## 静态门

- ruff（CI 范围 `frontier_agent/ apodex/ server/ benchmarks/ workflows/ plugins/ deploy/ tools/ scripts/`）通过；
- `import_smoke.py --stage 1` 通过（layering 规则）；
- pyright **0 errors**（`uv sync` 补齐 hf-space + web group 后与 CI 环境等价）。

## 放行声明

I3-7 重验全链通过且全部结果与 i0c-r4z 冻结版本一致（revs 逐一复现、policy 逐字段一致）。
**M6 仍不在本轮放行**——按任务清单 §3.6 与架构 §12.1 纪律，须经**独立复核 + U 具名签认**。
I3-6 后任何影响运行的变化将使最终报告失效，回到新的版本冻结与 I3-7。

## 链上收口

本 README + tasks.md §0/I3-7 回填 → 冻结修订 **i0c-r5b**（parent=i0c-r5a；archive-first 归档
tasks.md 改前字节 == r5a 绑定 `fd254523…`、验证器改块前字节 == r5a 绑定 `971312ae…`；
验证器追加 r5b 语义门块）→ 三门验证器 exit 0。

## 纪律核对

触及字节 = 本审计目录（重建/评分/电池/legacy 脚本与产物 + lane 日志）+ tasks.md 回填
（经 i0c-r5b 入链重绑）+ 冻结链文件（i0c-r5b.json / freeze-manifest.json /
validate_i0c_freeze.py）。写库仅限隔离沙箱（重建/恢复语义内）与临时第三库（用后 DROP），
生产库 5432 零触碰；零模型；留出零读取；不 commit / 不 publish / 不重摄入（恢复步重建为
teardown+同版本重建，非重摄入——revs 与冻结报告逐一复现）。
