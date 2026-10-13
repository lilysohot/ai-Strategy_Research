# 并集裁定（Union Adjudication）— 2026-10-13

**裁定权威声明：以 `claims-r2-role-isolation/adjudication/worksheet.json`（下称 A，U 于 2026-10-12 核实署名，reviewer=xyl × 222 行）为准。**
本会话的 67 机械预填（下称 B，`drafted_by=agent`，未署名）整体降级为**提案**，其与 A 的 29 行分歧逐条列出，**建议全部维持 A**；如你对个别行有不同判断，请在该行"U 改判"处批注，其余行自动生效。

## 一、两份来源

| 版本 | 文件 | 形态 | 分布 | 性质 |
|---|---|---|---|---|
| **A（权威）** | `claims-r2-role-isolation/adjudication/worksheet.json`（2026-10-12） | 222 条、完整契约 11 字段 | matched 26 / dup 1 / ce 190 / oos 5 | **U 已核实**（含 2026-10-12 三行 U 亲自校准撤销记录） |
| B（提案） | `evidence/67-…/prefill-draft-203.json`（2026-10-13） | 222 行、机械草稿 | matched 33 / dup 8 / ce 181 | agent 提案，difflib≥0.75 机械匹配，未署名 |

## 二、A 与 B 的分歧：29 行（U 口径的"15 条"为低估）

分布：ce→dup 4 ｜ **ce→matched 13** ｜ matched→dup 4 ｜ dup→ce 1 ｜ **oos→ce 5** ｜ matched→ce 2

## 三、逐条裁定（建议：全部维持 A）

### 3.1 A 判 matched、B 提议降级（6 行）——维持 A

| 候选 | A | B 提议 | 维持 A 的依据（A 原理由） |
|---|---|---|---|
| itm_7ba3125d | matched NT-I03 | duplicate | 「73.91 亿只盖 0.32 倍」与 NT-I03 同义（fact/evidence） |
| itm_7e31e390 | matched NT-I04 | duplicate | 「现金质量差」与 NT-I04 同义 |
| itm_2f600383 | matched NT-I10 | duplicate | 「毛利率再掉或 Rubin 延期→倍数受冲击」即 NT-I10 |
| itm_c8690f1b | matched NT-I35 | correct_extra | 与 NT-I35「无差别相信所有份额陈述」同一前提 |
| itm_5e44b07c | matched NT-I37 | correct_extra | 与 NT-I37「1.6T 不及预期解释 800G」同一解释机制 |
| itm_e6a5f468 | matched NT-I21 | duplicate | 命题即「CPO 市场成熟度不高」 |

### 3.2 A 判 ce/oos、B 提议升级 matched（13 行）——维持 A（B 为机械过匹配）

关键证据：其中 **3 行（itm_42ffb8ce / itm_09fc1a90 / itm_f2e29952）A 的理由是【2026-10-12 U 校准裁定】亲自撤销 matched**——金标为「被转述且被质疑的预测」(perspective=quoted_other)，机械匹配无法看到这个口径。其余 10 行 A 的理由同样成立（缺主语、类比式问句、片段成因、口径不同等）。逐行：

| 候选 | A | B 提议 | A 原理由（摘要） |
|---|---|---|---|
| itm_42ffb8ce | ce | matched | **U 校准撤销**：金标为被转述且被质疑的预测 |
| itm_09fc1a90 | ce | matched | **U 校准撤销**（同上口径） |
| itm_f2e29952 | ce | matched | **U 校准撤销**（同上口径） |
| itm_7c8488b0 | ce | matched | 正确观点但不在 48 金标内 |
| itm_99362251 | ce | matched | 利润质量观点，不在金标内 |
| itm_36692d3e | ce | matched | A股唯一 NVIDIA 整柜代理叙事，不在金标内 |
| itm_ec18c384 | ce | matched | 类比式问句，非金标肯定断言 |
| itm_a79b0be0 | ce | matched | 候选未提「海外产能」，仅为片段 |
| itm_bd6cd536 | ce | matched | 主语不同（交换机侧 vs CPO 成熟度） |
| itm_bf5fa66f | ce | matched | NT-I38 前半句，缺后半限定 |
| itm_703720fd | ce | matched | 命题缺主语「128端口产品」 |
| itm_a41addfc | ce | matched | 缺主语「128端口光波导」 |
| itm_fc120f1f | ce | matched | NT-I37 已另由候选命中，本为片段 |

### 3.3 A 判 out_of_scope、B 提议 correct_extra（5 行）——维持 A

「mx-xuangu 行情日标签」「什么状态？」「二季度 800G 出货未达预期的原因是什么？」「谁说的？」「这个不太对」——均为**非实质命题片段**（追问/元评论/数据源标签），out_of_scope 正确。B 的机械规则无法识别"无命题内容"。

### 3.4 其余零星（4 行）——维持 A

itm_db11557f（ce→dup：与归母 237.40 亿差 7.56 亿非经常，不在金标内）、itm_17b13257（dup→ce：NT-I07 已被 itm_17b… 前件命中——见 A 理由）、itm_cf8baa3c（ce→dup：出货节奏观点非 NT-I32 独立条）、itm_64a666c2（ce→dup：27 年口径与 NT-I22 26 年不同）。

## 四、并集生效后的裁定状态

| 集 | 条数 | matched 金标 |
|---|---|---|
| A（池内 222，权威） | 222 | 26 |
| r5 签认批（I06/I41） | 15 | NT-I06（+1） |
| base 签认批 | 16 | NT-I13/I14/I15/I16/I17/I42/I43（+7） |
| **合计** | **253** | **34 / 48 = 0.708** |

与已签 r5/base 的占用核查：**完全一致**（I05/I07/I08/I41 的池内占用者与 r5 声称逐一同）。

## 五、诚实的出分前景

- 召回：34/48 = **0.708 < 0.85 → 门 33 仍不过**。缺口 = 14 条无任何候选匹配的金标（NT-I09/I19/I23/I24 等）——它们是真实的 FN，不是流程问题。
- precision：由 A 的 190 ce + 6 ce（r5/base）入分子、1+3 dup + 7 matched 对应的候选计入后可精确计算——装配后出。
- **下一步（零调用）**：A 已是完整契约形态，可直接装配 222 条 + 已签 31 条 → 出门 33 的真实分数（召回 0.708、precision 待算）→ 这就是"诚实出分"。装配脚本 + validate.py 自检由你一声令下。

## 六、U 待办

1. 若接受"全部维持 A"：回"确认并集"，我执行装配与出分（零调用）。
2. 若对个别行有不同判断：在本文档对应行批注"U 改判：xxx"，我按改判装配。
