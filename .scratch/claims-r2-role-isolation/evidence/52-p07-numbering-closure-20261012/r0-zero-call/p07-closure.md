# P07 · 编号歧义收敛（Wave 0 收尾，零调用）

- 来源缺陷：**D10「编号冲突（两个 41）」**
- 性质：零调用；**不改任何既有文件字节**（`in_place_edits = 0`）
- 编号裁定人：U（2026-10-12 委托本会话选定"最佳编号"）

## 一、编号裁定（最终）

| 目录 | 归属 | 依据 |
|---|---|---|
| **`41-items-chain-accounting-20261012`** | **保留 41** | 存在对应 Issue 文件 `issues/41-items-chain-accounting-freeze.md` ⇒ 编号与 Issue 号对齐，这是唯一可判定的权威对应 |
| `45-contract-v4-draft-20261012` | **保持 45**（原为 41，已改号） | 它是 Issue 34 工作流的契约产物，**无 Issue 号主张**；顺延至下一个空号 |

**规则（此后适用）**：整数编号全局唯一；凡有对应 Issue 的目录**优先占用该号**，无 Issue 号主张者顺延。改号记录见 `45-…/r0-zero-call/rename-record.json`（`sha256:` 已存）。

## 二、残留失效引用清点

对全树 grep `41-contract-v4-draft` 得 5 处，分类如下：

| # | 位置 | 性质 | 处置 |
|---|---|---|---|
| 1 | `34-…/chain-report.md:16,423` | **历史记载**（记录改号事实，应当保留旧路径） | 不动 |
| 2 | `45-…/rename-record.json` | **历史记载**（old→new 记录） | 不动 |
| 3 | `45-…/MANIFEST.json`（1 条输入键） | **活引用断裂** | 见 §三 |
| 4 | `45-…/draft_contract_v4.py:10`（用法注释） | **活引用断裂**（照抄命令会失败） | 见 §三 |
| 5 | `41-items-chain-accounting-…/r2-proposals/contract-v4-draft.md:80` | **活引用断裂**（指向不存在的审阅件） | 见 §四 |

实测：`45-…/MANIFEST.json` 的 8 条输入键中**仅 1 条断裂**（`41-contract-v4-draft-…/preregistered-contract-v4.json`），其余 7 条存在（相对仓库根解析）。

## 三、为什么 #3/#4 不就地修（关键判断）

`45-…/draft_contract_v4.py` **自带 fail-closed 签认护栏**（`:281-297`），它会在重跑时拒绝覆盖 `contract-v4-review.md`。因此：

- **不能**用"重跑脚本"来再生成 `MANIFEST.json`（会被护栏拒绝，且即使用 `--force` 也会**抹掉 U 的签认**——这正是护栏要防的事）。
- 手改 `MANIFEST.json` 会让它与脚本产出**不再一致**，比一条已知的过期输入键更糟。
- 单独改 `draft_contract_v4.py` 的注释会使它的哈希与 `45-…/MANIFEST.json`、`45-…/preregistered-contract-v4.json` 中已记录的值不符。

⇒ 依 write-once 约定：**保留字节，以本记录登记**。下次该目录产生新版本记录时，一并把 #3/#4 修正。
修正后的正确值：
- #3 输入键应为 `.scratch/claims-r2-role-isolation/evidence/45-contract-v4-draft-20261012/r0-zero-call/preregistered-contract-v4.json`
- #4 用法命令应为 `uv run python .scratch/claims-r2-role-isolation/evidence/45-contract-v4-draft-20261012/r0-zero-call/draft_contract_v4.py`

## 四、#5 的处置（跨并行目录，需你一句话）

`41-items-chain-accounting-…/r2-proposals/contract-v4-draft.md:80` 写的是
`../41-contract-v4-draft-20261012/r0-zero-call/contract-v4-review.md`，应改为
`../45-contract-v4-draft-20261012/r0-zero-call/contract-v4-review.md`。

该文件属并行会话目录；`rename-record.json` 已把处置权记为 `parallel-session / U`。**本会话未写入**。这是一行路径修改，不涉及签认件；你说一声我就改。

## 五、连带发现：护栏的诞生事故（补记，非 P07 范围）

`45-…/draft_contract_v4.py:281-283` 的注释记载了 D9 的**起因**：

> `Incident 2026-10-12: re-running this script silently erased a signature on contract-v4-review.md; the user only authorised revoking chain-report.md.`

即：**重跑该脚本曾静默抹掉 U 在 `contract-v4-review.md` 上的签认**。这有三点含义：

1. D9「护栏只在单个脚本」不是抽象风险，本项目**已经真实发生过一次**签认被脚本抹除。
2. P06「不逐个改写历史脚本、改为机制+执行器+例外登记」的方向与事故教训一致：真正会伤人的是**重跑**，而 P06 的执行器把"新增未护栏写入者"变成失败条件，并对历史写入者登记"禁原地重跑"。
3. P06 扫描器**未漏报**此项：`guarded = 3` 中即含 `45/…/draft_contract_v4.py`（`inline_guard`），其保护对象含 `contract-v4-review.md`（`sha256:753532e8…`，U 已签 v4 的审阅件）。本会话曾一度怀疑漏报，实测证伪，记录于此以免重复怀疑。

## 六、不宣称

- 本记录**不修改**任何既有文件；#3/#4/#5 的字节仍是原样。
- 编号裁定只解决"目录号唯一性与 Issue 对齐"，不改变任何产物的哈希与效力。
