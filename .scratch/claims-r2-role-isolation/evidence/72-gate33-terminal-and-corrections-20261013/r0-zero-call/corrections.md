# 门 33 终态记录与四处表述更正（零模型调用）

- 2026-10-13　授权：U（xyl）2026-10-13：不改金标、不扩大样本 ⇒ 门 33 判为不可达、如实记档
- 谓词：**达标** = 7 条判据全 PASS；**不可达** = 在冻结金标字节不变、样本不扩大、既有具名裁定不变下无法同时 PASS

## 一、终态

**门 33 = FAIL（不可达）**（未过判据：[1, 2, 7]）

| # | 判据 | 门槛 | 实测 | 判定 |
|---|---|---|---|---|
| 1 | target_recall_overall_min | >= 0.85 | 34/48 = 0.708 | **FAIL** |
| 2 | target_recall_per_source_min | >= 0.80 每源 | 源1 20/22 = 0.909；源2 14/26 = 0.538 | **FAIL** |
| 3 | candidate_precision_min | >= 0.80 | 30/31（240/248） | **PASS** |
| 4 | unresolved_candidates_max | = 0 | 0（A 池 {'correct_extra': 190, 'matched': 26, 'duplicate': 1, 'out_of_scope': 5} + 签认批 {'correct_extra': 16, 'matched': 8, 'duplicate': 7}） | **PASS** |
| 5 | accepted_records_total_min | >= 40 | 242（verdict 口径；评分器导出 tp+ce = 240） | **PASS** |
| 6 | accepted_records_per_source_min | >= 20/源 | {"源1": 117, "源2": 130} | **PASS** |
| 7 | high_risk_item_assertions_required | 16/16 全覆盖 | 8/16；未中 ['NT-I09', 'NT-I19', 'NT-I38', 'NT-I39', 'NT-I45', 'NT-I46', 'NT-I47', 'NT-I48'] | **FAIL** |

## 二、为什么不可达

- 判据 7 缺口 8 条：可通过复核裁定回收 ['NT-I09', 'NT-I19', 'NT-I38', 'NT-I39', 'NT-I48']，**改判也无法回收（本轮的最后阻塞）** ['NT-I45', 'NT-I46', 'NT-I47']
- 原因：NT-I45/I46/I47 的候选与金标逐字相同（sim=1.0），但 U 于 2026-10-12 亲自撤销其 matched，理由为金标属『被转述且被质疑的预测』(perspective=quoted_other, source_stance=challenged)，候选为材料自身陈述。该口径由 U 本人设定，任何执行动作（补抽/降门槛）都无法翻回。

| 其他出路 | 为什么不行 |
|---|---|
| targeted_reextraction | 补抽产出相同片段，会被同一口径再判 correct_extra |
| lower_numeric_threshold | 即使把 overall/per-source 降到实测值以下，判据 7 仍为 13/16 |

反事情景（evidence/71）：

- 保留 U 校准（S3_A_B_minus_u_calibration（evidence/71））：召回 0.938、断言 13/16 → **still FAIL**
- 全部 14 条改判（S2_A_and_B（evidence/71））：召回 1.0、断言 16/16 → **PASS**（但这属于改判，不是原标准下的达标）

## 三、四处表述更正（旧件字节与哈希留存，未编辑）

| # | 既有表述 | 出处 | 机器实测 | 取代证据 |
|---|---|---|---|---|
| 1 | 缺口为真实 FN（金标无候选匹配），非流程问题 | `evidence/69-union-adjudication-20261013/r1-score/gate33-honest-score.json:88` | 14/14 条 FN 均有同源近似候选；『无匹配』字面为真，读作『模型未产出』为假 | `evidence/71-fn-attribution-20261013/r0-zero-call/fn-attribution.json` |
| 2 | 14 条 FN 为真实抽取覆盖缺口（三次独立抽取均未覆盖） | `evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:26-30` | 0 条落在 evidence/32 记录的 9 个未产出槽；0 条为『池内无近似候选』 | `evidence/71-fn-attribution-20261013/r0-zero-call/fn-attribution.json` |
| 3 | 8 条未过断言全部属于源2 文档段 | `evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:17；report.md:14` | NT-I09、NT-I19 属于源1；与该文件自身判据 2『源1 20/22』自相矛盾 | `evidence/71-fn-attribution-20261013/r0-zero-call/fn-attribution.md` |
| 4 | 源2 召回 0.538 + 8 条断言未过：需对源2 对应片段定向补抽 | `evidence/70-closure-20261013/r0-zero-call/closure.md:29；gate33-full-verdict.md:34` | 补抽产出相同片段，会被同一裁定口径再判 correct_extra；缺口在裁定口径而非抽取 | `evidence/71-fn-attribution-20261013/r0-zero-call/fn-attribution.json` |

## 四、记录之间的分歧（仅登记，不判定）

| 项 | 一处记录 | 另一处/机器值 | 影响 |
|---|---|---|---|
| accepted_records_total | 242 | 240 | 两者均 >= 40，判据 5 结论不变；仅记录分歧，不判定谁对 |
| 8 条断言所属源 | 全部源2 | 源1 ['NT-I09', 'NT-I19'] | 影响判据 2/7 的归因表述，不影响 FAIL 结论 |

## 五、本裁定不影响的项

- 发布标准（结构完备性）与门 33 阈值/金标解耦：store.py 对 gold/recall/assertion 零引用；按 U 裁定走『显式缺口』路线

仍开放（不阻塞本记录）：

- issue 33 §7 gold_consumption_and_scoring 授权行仍为空 —— 未具名前保持挂账
- ef08 槽 r4 模型名偏差（已申报，未处置）
- 预注册与授权文件未互链（轻微）

## 六、复现

```bash
uv run python .scratch/claims-r2-role-isolation/evidence/72-gate33-terminal-and-corrections-20261013/r0-zero-call/build_terminal_record.py
```
