# NT-I43 polarity 表示缝勘误登记 — 签认件

- 编号：111 号（`evidence/111-i43-polarity-seam-erratum-20261015/r0-zero-call/`）
- 日期：2026-10-15
- 状态：**草案待签**（签名栏全部留空；本件正文状态行在签认后不作就地修改，以签名栏 + 生效件为准，按 108/109 号本链统一读法）
- 被签对象：`i43-polarity-seam-erratum.proposed.json`（草案哈希见同目录 MANIFEST.json）

## 一、签认事项（covered）

签认即确认以下三点：

1. **归因登记**：NT-I43（items 哨兵 + critical）在 109 号 P5 判定中未匹配，归因 = 金标侧 polarity 表示缝（原文字面否定副词「不再」在候选侧读为 negated、金标侧读为肯定式条件 affirmed，契约要求 polarity 一致 ⇒ 逐字候选不能 matched）+ 复合载体 `itm_8e932aaf49806db7` 已被 NT-I13 占用（gold_split_finer_than_candidate）。**非抽取覆盖缺口。**
2. **取代读法**：此后引用 P5 哨兵读数 10/11 与判档 FAIL（单轴）时，须连带引用本件——NT-I43 未中系标注侧成因，不构成抽取质量缺口的证据；不得被引用为「抽取模型漏抽该内容」的证据。
3. **字节不动**：冻结金标、门 v3 及其 11 项哨兵清单、评分契约、评分器、P5 放行件、gen-2 发布件与生产 store 的所有字节均不改；本件只登记归因与读法。

## 二、明确不覆盖（does_not_cover）

- 不修订金标 NT-I43 的 polarity/proposition 字段；
- 不把 NT-I43 移出哨兵清单、不修订门 v3；
- 不重算 P5 分数、不改判档；
- 未来如需以哨兵 11/11 或改判读数出分，须另立金标勘误 + 门修订的独立签认（Issue 23 / 75 号模式），本件不预授权。

## 三、证据基础

见 `i43-polarity-seam-erratum.proposed.json` 的 `seam_description.evidence` 五条（66 号逐字候选行、70 号分层、109 号 batch-01 第 4 点、P4 缺口分析 `in_set_repair_possible=false`、35 号审计金标内部自洽）。另：U 2026-10-15 会话口谕——I43 金标标注与原文存在语义问题、原因已在此前文档说明（文档位置未在档案中定位到，按口谕登记）；「先把 I43 先完结，不能成为接下来的阻碍」。

## 四、签认

```
reviewer: xyl
adjudicator:xyl
signed_on:2026-10-15
```

（签认后由 `apply_i43_erratum_signoff.py` 零调用出生效件 `i43-polarity-seam-erratum.json`；脚本校验本件哈希与草案一致、签名栏非空才出件，且永不覆盖既有生效件。）
