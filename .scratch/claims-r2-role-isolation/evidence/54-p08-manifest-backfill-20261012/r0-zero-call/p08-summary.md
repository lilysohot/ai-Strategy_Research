# P08 · r0 目录 MANIFEST 补齐 / 声明不补（Wave 0 收口）

- 来源缺陷：**D11 `scan-MANIFEST-missing`**（32/33/34/35 与 41-items-chain-accounting 的 r0）
- 零模型调用；**只新增文件，不改任何既有字节**（`in_place_edits = 0`）

## 判定规则

> 本会话工作流的目录 ⇒ 回填 MANIFEST（哈希可核）；并行会话的目录 ⇒ 声明不补（避免形成第二个相互竞争的真相源，亦遵循既有跨目录边界）。

## 逐目录结果

| 目录 | 处置 | 域内产物 | 声明输入 | 见证文件 |
|---|---|---|---|---|
| `32-items-v6-reasoning-refreeze-20261011/r0-zero-call` | written | `freeze-manifest.json` | 7 | 9 |
| `33-items-quality-scoring-20261011/r0-zero-call` | written | `workbench.json` | 3 | 7 |
| `34-chain-root-cause-audit-20261011/r0-zero-call` | written | `chain-audit.json` | 5 | 3 |
| `35-gold-audit-20261011/r0-zero-call` | written | `gold-audit.json` | 0 | 5 |
| `41-items-chain-accounting-20261012/r0-zero-call` | **声明不补** | — | — | — |

## 为什么并行目录声明不补

- `41-items-chain-accounting-20261012/r0-zero-call`：并行会话目录：其自身的会计记录（accounting-checks.json 已含 14 条 inputs 与 checks）即该会话的真相源；本会话另写一份 MANIFEST 会形成第二个相互竞争的真相源。且本会话此前已多次遵循「不写入并行目录」的边界（见 45/rename-record.json 的同条规定）。

## 回填件的效力边界（必须随件阅读）

- 回填件证明的是**回填当日**的字节，**不**证明该目录自创建以来字节未变。
- 它不是该目录诞生时的清单；`kind = retro_manifest` 已标明。
- 32/33/34 的声明输入取自各自域产物原有的 `inputs` 字段；35 的 `gold-audit.json` 未声明 `inputs`，
  故改为**递归收集其内的 sha256 值**并在 `declared_inputs_source` 显式记明，不作推断。
- 回填件经 `tools/evidence_guard.write_once` 写入 ⇒ 已存在或已签认时拒绝覆盖（P06 护栏的首次直接应用）。
