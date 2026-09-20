# P-1 冻结链归位（先于一切检索改动）

Status: needs-triage
Type: task
Depends: 无（**必须先于 01**）

## 问题

i36 §5 报告：全链 `i0c-current` 为 **red（8 条失败）**，全部是本次会话开始前已存在的工作树未冻结漂移。**基线是红的，任何修复增益都读不准。**

8 条：

| # | 路径 | 漂移内容 |
|---|---|---|
| 1 | `plugins/corpus/scoring.py` | 工作树 whitespace-norm `f61573d7` vs r19/r21/r39 绑定严格码位包含 `bf9c8b80` |
| 2 | `plugins/corpus/preparation/readers/pdf_reader.py` | reader-pdf-5 实现（i1-r4 绑定的是 reader-pdf-2） |
| 3 | `plugins/corpus/preparation/readers/base.py` | 同上（缺口码词表文档同步） |
| 4 | `tests/test_corpus_preparation_clean.py` | 随 reader-pdf-5 演进 |
| 5 | `tests/test_corpus_preparation_readers.py` | 同上 |
| 6 | `tests/test_corpus_scoring.py` | 随 whitespace-norm 新增用例 |
| 7 | `docs/plan/corpus-ingestion-rebuild-tasks.md` | 文档演进 |
| 8 | `docs/plan/claims-market-closed-loop-plan.md` | 同上 |

## 这不是"重绑一下就完事"

必须先做一个**决策**：reader-pdf-5 与 whitespace-norm scorer 是否整体采纳。

- **采纳** → 新建 `i0c-r41`，绑定上述 8 条的新字节。若采纳 whitespace-norm 语义，**必须另起新冻结修订重建 `scoring-input-manifest.json` 血缘**（i36 §4 原话：不得在单一回归中用空白 scorer 混入）。
- **不采纳** → 按 `git show HEAD:<path>` 逐字节还原工作树，核对 sha256 与 r39 绑定相等。

两条路**都不得**就地调参或只改一半。

## 另需单列跟踪（不在本票内解决）

M5 F3：`validate_i1_freeze.py` 对工作区 13 项失配 = i1-r3 绑定未随 I2 合法改动更新。建议随 `i1-r5` 重绑。

## 验收

```bash
uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py; echo "exit=$?"
uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i3_2_completion.py
```

- 判定必须用 `text.rstrip().endswith("exit=0")`，不得用 `"exit=0" in 日志`（失败文案会自身命中）
- `i3_2_complete=true`
- 语料族回归不回退：`uv run pytest tests/test_corpus_*.py -q` → 651 passed / 12 skipped

## 不做

- 不修改任何被绑字节的**语义**
- 不在本票内顺带做检索层改动（那会把归因搅浑）
