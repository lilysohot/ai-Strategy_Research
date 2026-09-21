# i1-r6 冻结重绑（B1 收口：i1 冻结门转红）— 审计报告

- 生成：2026-09-21；类型：**冻结记账修订**（不改任何实现/测试运行字节、不触金标/scorer/I2 检索层）
- 触发：`audits/20260921-spec-closure-audit/review.md` 的 B1（实测 `validate_i1_freeze.py` exit 1）
- 新修订：**`i1-r6`**（parent=`i1-r5`，append-only）；生成器：本目录 `gen_i1_r6.py`（支持 `--no-write`）
- 结论：**三门全绿恢复**（i1 exit 0 / i0c exit 0 / i3_2 exit 0），非回归与静态门无变化。

## 一、根因（机读）

| 事实 | 值 |
|---|---|
| i1-r5 绑定 `tests/test_corpus_preparation_admission.py` | `ccfd2dd833b9…`（与 i0c-r4n 一致） |
| 工作树当前字节 | `6adbb2745c90…`（`sha256sum` 实测） |
| 变更来源 | **r4s**：为修 M5 复核 MISS②（dev-lane 用例在 i1 守卫下读越界来源），把 9 条 dev-lane 用例拆到新文件 `tests/test_corpus_dev_lane.py`，本文件恢复 i1 纯净 6 份材料语义 |
| 为什么红 | i0c-r4s 重绑了该路径（i0c 链绿），**i1-r5 未同步** ⇒ `r5.binding[tests]` 失配 |

## 二、动作（append-only，不改写历史）

1. `binding.tests`：重绑 `tests/test_corpus_preparation_admission.py` = 当前权威字节（`6adbb274…`，与 i0c-r4s 同值）。
2. `binding.freeze_validator`：重绑 `validate_i1_freeze.py`（`71d8d60b…` → `6a6e7c06…`）——新增 i1-r6 块（parent / 绑定核验），
   并让 i1-r5、i1-r3 对该两个路径按 **supersession** 豁免（最新修订优先）。
3. **archive-first**（写入前完成，`freeze_utils.assert_archives_faithful` 通过）：
   - 被取代的 i1-r5 声明字节（`ccfd2dd8…`）已不在工作树，取自 r4s 归档
     `audits/20260922-r4s-rebind/before-r4s/test_corpus_preparation_admission.py.pre-r4s`（sha 实测一致），
     复制入 `before-r6/tests/…`；
   - pre-r6 校验器字节（`71d8d60b…`）归档为 `before-r6/freezes/validate_i1_freeze.py.pre-r6`；
   - 记录落 `before-r6/archive-provenance.json`。
4. `freeze-manifest.json` 追加条目（`i1-r6` / sha / parent=i1-r5 / created_at）。

## 三、证据（本次实跑）

```
uv run python .../freezes/validate_i1_freeze.py
  → freeze chain verified: … ; i1-r5 supersession -> i1-r6 (admission test + i1 validator rebind)   exit=0
uv run python .../freezes/validate_i0c_freeze.py        → i0c freeze chain verified …             exit=0
uv run python .../freezes/validate_i3_2_completion.py   → "i3_2_complete": true                    exit=0
uv run pytest tests/test_corpus_*.py -q                 → 751 passed, 12 skipped
uv run ruff check frontier_agent/ apodex/ benchmarks/ workflows/ plugins/ deploy/ tools/ scripts/ → All checks passed
uv run pyright                                          → 19 errors（与基线一致，均为 sqlalchemy/argon2 缺依赖）
```
完整日志：本目录 `freeze-validation.txt`。

**负例探针（证明门真的生效，不是假绿）**：in-process 篡改 `digest()` 让 admission 测试恒返回错值 →
```
FREEZE CHECK FAILED: r6.binding[tests]: tests/test_corpus_preparation_admission.py 哈希失配或缺失
freeze chain verification FAILED: 1 error(s)
```
且 **r5 不再报该路径**（supersession 生效）⇒ 门有效 + 豁免有效。

**可重入性**：`gen_i1_r6.py --no-write` 复跑输出稳定；补丁/manifest 条目/归档均幂等命中（`created_at` 固定复用）。

## 四、纪律
不 commit、不 publish、不重摄入；不改实现/测试运行字节；不改 scorer/金标；不改 `max_chunks_per_top_document=8`。
本修订性质为**记账**：不改善任何 M6 判据（spec §14.6 的 B2–B7 仍未闭环，须 U 裁决）。
