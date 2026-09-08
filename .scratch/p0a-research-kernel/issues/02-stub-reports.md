# 02 · 手写 stub 研报（5 份）

Type: task
Status: closed
Blocked by: 01

**Goal**: 产出 P0a 专用的假研报，让 P0a 的链路可以被**手工预期**。

**Why it matters**: stub 的目的不是模拟真实研报，而是**让你事先知道正确答案**——
只有知道答案，才能判断 Agent 到底读了没有、真的调工具没有。
若用无意义 lorem ipsum，P0a 的验收将不可判定。

**Work**
放 `tests/fixtures/stub_reports/`（进 git，作为回归测试资产），5 份 markdown：

| 文件 | 内容要求 | 用于验证 |
|---|---|---|
| `R01_看多.md` | 明确目标价（如「目标价 1720 元」）、营收预测（「同比 +23.4%」）、一段 fact | 数字溯源、fact 抽取 |
| `R02_看空.md` | 与 R01 **同标的反向观点**，带一个 forecast 数字 | **分歧呈现**（不平均化） |
| `R03_风险提示重复.md` | 含一段与 R01 **逐字相同**的风险提示段落 | 近重复折叠（P0b 验证，P0a 先埋点） |
| `R04_失效条件.md` | 明确写出「若季度营收同比转负则逻辑失效」 | `invalidation` 抽取 |
| `R05_无数字.md` | 纯定性论述，无任何数字 | 验证 Agent 不会为了凑数而编数字 |

**关键要求**
- 每份顶部带 `source_ref` 标识与 `published_at`，格式与 P0b 的 `Record` 一致
  （`source_ref: stub:R01`、`page: 1`）——保证 P0a 产出的 evidence 结构与 P0b 完全兼容
- 数字刻意写死且唯一（避免多处出现同一数字导致溯源校验产生歧义）

**Acceptance**
- 5 份文件落 `tests/fixtures/stub_reports/`
- 人工可回答：「R01 的目标价是多少」（答案唯一且已知）
- `source_ref` 格式与 `docs/p0-implementation-spec.md` 第 4.3 节的 `Hit` 契约一致

## Answer

5 份落 `tests/fixtures/stub_reports/`（进 git，作为回归测试资产）：

| 文件 | 埋点 | 独有数字 |
|---|---|---|
| `R01_看多.md` | fact + forecast + 一段风险提示（供 R03 逐字复用） | 目标价 24.50 / 营收同比 +23.4% / 毛利率 31.2% |
| `R02_看空.md` | 与 R01 **同标的反向观点**（分歧） | 目标价 15.80 / 同比 -4.7% |
| `R03_风险提示重复.md` | 与 R01 **逐字相同**的风险提示段落 | 无独有数字 |
| `R04_失效条件.md` | `invalidation` 抽取 | 「若季度营收同比转负，则「产能爬坡 → 收入增长」这条逻辑链失效」 |
| `R05_无数字.md` | 验证 Agent 不会为凑数而编数字 | **零数字**，并在文中明说这一点 |

- 顶部统一带 `source_ref: stub:R0N` / `page: 1` / `published_at` /
  `first_observed_at`，与 P0b 的 `Hit` 契约同形。
- 标的用虚构的 `LHXC.SH`（蓝海新材），刻意避开真实代码，
  免得演示被读成投资建议。
- 数字刻意唯一：24.50 只在 R01 出现，15.80 只在 R02 出现，
  溯源比对不会产生歧义。

**发现的坑**：`tests/test_p0a_chain.py` 第一版把 R04 的 quote 写成
「若季度营收同比转负则逻辑失效」——这是**归纳后**的话，不是原文。
硬闸①的逐字比对直接失败。`evidence.quote` 必须是原文子串，标点都不能改。

## Comments
