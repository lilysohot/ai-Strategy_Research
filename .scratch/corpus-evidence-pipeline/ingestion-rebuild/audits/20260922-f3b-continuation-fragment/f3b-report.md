# F3-B 复验报告：读取侧续接片段聚合（i0c-r4u，路径 B）

- 日期：2026-09-22；裁决：U 具名（按路径 (B) 执行——仿 F4 `cross_boundary` 先例，免重摄入）
- 性质：只读回放 + 产品路径比对，0 model calls；未写库、未重摄入、未 commit/publish、未改 clean 判定

## 根因（承 f3-report.md）

F3 单元级判定已生效（ord717 NOISE→KEPT，`i0c-r4p`）但事实句被版面切成 kept 前半
（ord717，止于「…4.06%的股」）+ NOISE/`disclaimer_section` 尾片段（ord718，仅「份。」）；
块装配只收 kept 单元 ⇒ 引文「…4.06%的股份。」逐字不可承载。F3 修"该不该剔"（判定粒度），
真根因是"切分/装配粒度"。

## 修复内容

- [cross_boundary.py](../../../../../../plugins/corpus/preparation/cross_boundary.py)：
  `aggregate_band_chunks`/`_merge_chunk` 扩展 `stitch_continuation`（默认开）——kept 单元
  句中截断（raw_text 不以 `_SENTENCE_TERMINAL` 收尾）且紧邻下一 ordinal 的 NOISE 单元以
  句末标点收尾（拼接即补全句子）并同页 ⇒ 按 (ordinal, unit_id) 保序聚合进块证据（内容哈希
  fail-closed 同 F4）；`_BOUNDARY_UNITS_SQL` 增第三支候选（块内 kept 前驱的 NOISE 单元）。
- `service.py` 字节零改动：`search_bands` 既有 `aggregate_band_chunks` 接线直接获得续接聚合。
- 常驻测试：`tests/test_corpus_selection.py` +4 条 I-CONT-1（正向拼接还原并断言序/span 自洽 /
  非句末片段不聚合 / 截断头+相邻+同页条件缺一不可 / 幂等不重复）。

## 谓词普遍性（非金标）

三层扫描（`f3-fragment-scan.json` + 本目录精化扫描，口径记录于 i0c-r4u notes）：

- 裸放宽（任意 NOISE + 句中截断）：全库 132 处，混入页眉/页脚/目录紧邻；
- 精化（句中截断 + 尾片段以句末标点收尾）：8 builds 仅 ord717/718 一处（company-007/e1）。

机制普遍（版面切句 × kept-only 装配的交集对任何未来摄入语料成立），触发极窄（判别力来自
句末标点结构特征，非金标）。

## 复验结果（[f3b_replay.py](f3b_replay.py)，A/B 仅差 `stitch_continuation`）

| 判据 | 结果 |
|---|---|
| company-007/e1 | off=false → on=true（「…4.06%的股」+「份。」拼接还原） |
| 目标级（82 目标） | 零回退；新增恰为 {company-007/e1} |
| EvidencePass | off 18/24（=F4 基线）→ on 19/24 |
| 负例 | 6/6 retrieved_documents=0（off/on 均；认证路径 NO_MATCH 口径同 F2/F4） |
| 选择不变 | off/on SelectedBand 集相等；带宽 max 33 ≤ 49（provable_width_bound） |
| 产品一致性 | stitch=True 手工链 == `svc.search_bands`（逐字段相等，拷贝零漂移证明） |

## 验证与冻结

- selection 34 passed（30+4）；语料族 762 passed / 12 skipped（758+4，零回退）；
  ruff（CI 范围）All checks passed；触及字节 pyright 0 errors。
- 冻结 `i0c-r4u`（parent=`i0c-r4t`）：cross_boundary.py `85ee6be6`→`faa50936`、
  test_corpus_selection.py `1d0ecc29`→`b956fdc5`、validate_i0c_freeze.py→`d4ff1513`；
  manifest sha `4fb94875`；三门验证器 exit 0（i0c / i1 / i3_2）。
- archive-first：[before-r4u/](before-r4u/)（cross_boundary=`85ee6be6`、
  test_corpus_selection=`1d0ecc29`、validator=`17dc25d4`，sha256 已核与 r4q/r4t 绑定一致）。

## 残留

- company-003（doc rank 6 出 top-5，I-B1 词法副作用）与 company-008 其余目标仍归独立议题。
- M5 结论仍待独立复核 + U 签认（r4u 改 band 读取链证据聚合字节，m5_declaration=not_declared）。
