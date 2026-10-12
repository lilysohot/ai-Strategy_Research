# P06 · 签认护栏推广（Wave 0，零调用）

- 来源缺陷：**D9「护栏只在单个脚本（部分闭合）」**
- 性质：纯工程 / 零模型调用 / 零就地改动
- 产物：本目录（`guard-inventory.json` + 本文件 + `MANIFEST.json`）+ 仓库级工具 `tools/evidence_guard.py`、`tools/check_evidence_guard.py`、`tools/evidence_guard_exceptions.json`

## 一、为什么要"推广机制"而不是"逐个改写历史脚本"

护栏此前只存在于签认/合并脚本（`45`/`46`/`47`/`48`）。但**能毁掉已签认产物的其实是冻结与生成脚本**。直觉做法是把护栏逐个贴进那些脚本——**这在本项目里是错的**：

- 那些脚本**已经执行过**，其字节哈希被 `MANIFEST.json`／`README.md`／报告引用。改动字节 = 改写历史，会使其产物（已冻结金标、门 28、门 32 的冻结门）的**出处记录失效**，与 issue-34 §8（不就地修改既有产物）直接冲突。
- 实测爆炸半径：4 个脚本的哈希被 **4 件**产物引用（1 个 MANIFEST + 3 个 README/报告）。

**因此 P06 落的是"机制 + 执行器"**：单一护栏实现 + 可作门用的静态一致性检查 + 显式历史例外登记。任何**新增**的未加护栏写入者都会让检查以非零码失败——D9 的"部分闭合"由此关闭。

## 二、交付物

| 交付物 | 作用 |
|---|---|
| `tools/evidence_guard.py` | 单一护栏实现：`artifact_state()` 三态判定（missing/plain/signed）、`assert_writable()`、原子 `write_once()`（默认拒绝覆盖既有件，且在 `allow_overwrite=True` 下**仍然拒绝**已签认/冻结件） |
| `tools/check_evidence_guard.py` | 静态一致性检查：AST 解析每个脚本的写入目标 → 与文件系统实际签认状态交叉 → `violation` 时非零退出，可作 preflight/CI 门 |
| `tools/evidence_guard_exceptions.json` | 4 条历史例外登记（含理由、被引用处、`must_not: 原地重跑`） |
| `tests/test_evidence_guard.py` | 13 项：判定三态、结构化信号、**引用签名 ≠ 自身已签**（防误报）、md 审阅件、write-once、已签件拒绝覆盖、原子写、扫描器在真实目录上可作门 |

## 三、实测结果（`guard-inventory.json`）

```
scripts_scanned = 116
guarded         = 3
unguarded       = 113      ← 多数只写非签认产物（报告/json），非风险
violations      = 0        ← 新增未护栏写入者：0
legacy_exempt   = 4        ← 历史例外，全部登记
```

4 条历史例外（**不得原地重跑**）：

| 脚本 | 可写已签认产物 | 为何不改 |
|---|---|---|
| `10-…/r2/freeze_signed_gold.py` | `freeze-manifest.json`、`frozen-gold.json` | 产物是全部下游测量的分母；改脚本会使其在 `README.md`／`35/gold-audit.md` 的出处失效 |
| `28-…/r0-zero-call/freeze_items_only_plan.py` | `preregistered-gate.json` | 门 28 是 OPEN-1=A 的唯一权威阈值源，其冻结字节是口径依据；基准推进走 P13 新版本记录 |
| `32-…/r0-zero-call/freeze_two_arms.py` | `preregistered-gate.json` | 门 32 判据同轴问题走 P15 新版本判据提案 |
| `43-…/apply_v4_signoff.py` | `scoring-contract-v4.json`、`signoff-record.json` | **已被 `47/apply_v41_signoff.py` 取代**，后者自带护栏；v4 已 superseded_by v4.1 |

## 四、过程中被自检纠掉的三处错（记录以防重犯）

1. **误报**：初版把 `signed_by`/`复核人：` 当纯文本标记扫全部格式 ⇒ `p01-evidence.json` 因**引用** `contract_binding.signed_by` 被判"已签"。改为：结构化格式**只看结构**（`status` / 顶层 countersignature 等），文本标记只用于 `.md`。
2. **假阴性**：`frozen.atomic_write(...)` 这种限定调用被漏判 ⇒ 门 32 曾未进违约清单。已补 `Attribute` 分支。
3. **目标解析错**：`X.write_text(Y)` 的写入目标是 `X` 而非 `args[0]`（args[0] 是内容）⇒ 曾漏报所有 `write_text` 目标。

## 五、边界（不宣称）

- 本项**不改任何历史脚本**，因此**不是**"所有脚本都已加护栏"；它是"新增写入者必被拦截 + 历史写入者已登记且禁重跑"。
- 检查为**静态**近似：目标名动态拼接时记为 `<dynamic>` 且不参与签认交叉判定（可能漏，不会假报）。已知漏检类型已登记为 backlog。
- 本产物不产生任何门分数。
