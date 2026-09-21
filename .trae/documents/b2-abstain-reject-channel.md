# B2：产品负例 abstain 拒检通道接产品 — 实现计划

## Context

F1 负例 6→0 的判定层拒检兜底目前**只在回测脚本** `audits/20260921-f1-negative/f1_replay_readonly.py` 生效（按金标 NO_ANSWER 分支收紧），产品检索路径无 abstain 通道、`negative_query.py` 未入冻结链 → **产品侧负例恒为 6**（M6 `max_false_positives=0` 不达标）。

B2 目标：把 `negative_query.py` 的谓词接入产品检索返回路径，建立**无金标**的 abstain 拒检通道，使产品侧负例归零，同时不扰动有答案题 S1=66。

已确认取舍（U）：① **判定层统一拒检**（所有查询统一走，不动产品查询路径）；② **U 受控开关默认关**；③ 拒检时返回**空结果 + 拒检信号**。

硬约束（不违反）：判定层兜底优先于改检索词元路径；不调 `max_chunks_per_top_document=8`；**不触 `search_pg.py`/`scoring.py` 字节**；负例误报不回升；绑定/冻结 U 门控 + archive-first 新建冻结修订；不 commit/publish/重摄入（PG 写需授权）。

## 设计

### 开关键
新增 env 开关键 **`CORPUS_ABSTAIN_NO_ANSWER`**（取值 `on|off`，默认 `off`），在 `service.py` 服务层读取。完全镜像 `read_chain()` 模式（非法值 fail-closed 抛 `StoreError`）。off（默认）→ 判定恒 False，`search_with_coverage` 逐字节不变，S1 结构零扰动。

### 判定路径（挂载 & 候选原文来源）
挂载在 `CorpusService.search_with_coverage`（`plugins/corpus/service.py:916`）——`corpus_search` 工具走的产品默认路径。在计算命中后、return 前加一道门。开关关则该门第一步返回 False。

新增私有方法 `_abstain_decision(query) -> bool`：
1. 读开关；`cfg != "on"` 或 `read_chain() != "new"` → False。
2. `query_lexemes(query)` → `content_lexemes`；空则 False。
3. **DB 级 websearch AND 预检（主门，0 fetch）**：`search_chunks(tighten_no_answer_query(lexemes), limit=_ABSTAIN_PRE_CHECK_LIMIT=2000)`，空 → 返回 True（拒检）。
4. **单元级谓词保险带（仅收紧仍有命中才 fetch）**：对 tight hits 经 `fetch_verbatim` 取 `units[].raw_text` 跑 `is_relevant_candidate`，任一通过 → False（放行）；全部偶然命中 → True。

候选原文：`SearchPgHit` 只带截断 `snippet`/`title_text`，不含单元原文；谓词必须按 `unit.raw_text` 判定，故经 `read_pg.fetch_verbatim`（同 F1 回测脚本缓存去重做法）。主门（拒检共性情形）零 fetch，成本可控。

S1 保护是**结构性**的：实质答案单元在 websearch AND 下仍含全部内容词元、score 高且 `limit=2000` 必在其内 → 返回 False，产品路径原样返回；拒检只在"无任何全词元共现单元"（无实质答案）触发。

### 拒检信号返回表达
- `_score_negative`（`scoring.py:703`）只在 `documents` 非空时计 FP → **拒检必须返回空 hits**。
- 拒检分支返回：`return [], abstain_cov`，其中 `abstain_cov = coverage_snapshot(query_status="abstain")` 再 `update({"abstain": True, "abstain_reason": "no_answer_rejected"})`。已点验：`_coverage_from_row`（`read_pg.py:449/495`）对 `query_status` 原样透传、`query_status=="abstain"` → `availability=unknown`（不谎报）。
- `corpus_search.py` 空 hits 分支按 `coverage.get("abstain")` 分流：abstain → 新增 `ABSTAIN_HINT` 常量并顶层加 `"abstain": true`；否则走既有 `NO_COVERAGE_HINT`。空命中语义三分（检索失败 | no_match 无研报覆盖 | abstain 拒检）。

### 冻结：新修订 `i0c-r4t`
- archive-first：归档上一绑定字节（`service.py` r4q→`0227529c`、`corpus_search.py` r11→`8ff78c11`、`freeze_validator` r?）至 `audits/<slug>/before-r4t/`。
- `binding`：`chain_rebind_implementation`＝service.py（重绑）+ negative_query.py（**首次入链**）+ corpus_search.py（重绑）；`chain_rebind_tests`＝test_corpus_negative_query.py（**首次入链**）；`freeze_validator`。语义断言：service 含 `_abstain_decision`/`CORPUS_ABSTAIN_NO_ANSWER`、negative_query 含两谓词、corpus_search 含 `ABSTAIN_HINT`/`coverage.get("abstain")` 分流、测试含 B2 门名。r4t 在 r4s 后**最后 merge**（同 r4r 末尾合并纪律）。

## 修改文件清单

| 文件 | 动作 | 改动点 |
|---|---|---|
| `plugins/corpus/service.py` | 改 | `_ABSTAIN_PRE_CHECK_LIMIT=2000` 常量；`_abstain_decision`；`search_with_coverage` 加拒检分支 |
| `plugins/corpus/preparation/negative_query.py` | 复用（不改） | 纯复用 `content_lexemes`/`tighten_no_answer_query`/`is_relevant_candidate` |
| `plugins/tools/corpus_search.py` | 改 | `ABSTAIN_HINT`；空 hits 按 abstain 分流 + 顶层 `abstain` 字段 |
| `tests/test_corpus_negative_query.py` | 改 | 保留既有谓词测试；新增 B2 接线测试（off→不拒检；on+负例→空+信号；`_score_negative` 0 FP） |
| `.scratch/.../freezes/validate_i0c_freeze.py` | 改 | 加 r4t 校验块 + 成功打印追加 |
| `.scratch/.../freezes/i0c-r4t.json` 及 manifest | 新增/改 | 冻结载荷 + manifest 追条 |
| `.scratch/.../audits/<slug>/before-r4t/…` | 新增 | archive-first 归档 |

## 验证清单

- a) 负例归零（只读，需 PG 只读连接）：`CORPUS_ABSTAIN_NO_ANSWER=on` 下对 6 条负例题干跑产品 `search_with_coverage` → `hits==[]` 且 `coverage["abstain"] is True`；对照 `f1_replay_readonly.py` B 口径 `retrieved_documents=0` / `false_positives=[]`。
- b) S1/S2 不回退（只读）：on 下重放有答案题池 → `S1=66`/`S2=60` 不变；off 下 `search_with_coverage` 与 r4s 绑定行为一致（若回落 → 关开关 + 用 `before-r4t/` 回滚，记录归因）。
- c) 负例 FP 不回升（只读）：`score(observations, policy)` 对 6 负例 `false_positives` 空。
- d) 语料族回归（只读）：`uv run pytest tests/test_corpus_*.py -q` → `751 passed / 12 skipped`；新增 B2 用例通过。
- e) 三门验证器 exit 0（i0c/i1/i3_2）+ `ruff check` + `pyright`。

需授权项：① 沙箱库只读 PG 连接（负例/回归真库验证）；② 冻结修订建立与 U 门控在验证通过后由 U 签认再归档；③ 不 commit/publish/重摄入/PG 写。