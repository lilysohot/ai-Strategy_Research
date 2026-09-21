# 08 e1 `disclaimer_section` 判定粒度过宽

Status: needs-triage
Type: task
Depends: S5（已完成，机读判定已就位）
Layer: clean
Bound-byte impact: **是**（`plugins/corpus/preparation/clean.py`）
Reingest: **是**（改 kept 判定⇒全量重摄入）

## 问题

company-007/e1（spec §10.4 / §7.5 归因）：ord=717 整段分析师免责声明被 `noise/disclaimer_section` 剔，但同单元含**实质事实句**（华创云信 4.06% 持股）⇒ "规则过宽（粒度）"：整段一锅端，吞掉事实句。

## 改动面

- `disclaimer_section` 判定由**整段**改**句粒度**：仅当整段均为免责措辞时剔；含数字/实质事实句的区域降 **KEPT** 或保留实质句。
- 复用 S5 的 `NoiseVerdict.observed/threshold` 记录命中行/占比作依据。
- 阈值调整须具名签认（spec §11 纪律）。

## 不变量与反例

- **I-E3**：`disclaimer_section` 命中的 NOISE 区不得包含"含可复核数字事实"的句子（断言降 KEPT 或剔后作用域到句）。
- 反例：构造"免责段落 + 一句持股比例"的单元，断言仅免责句被剔、事实句保留为 KEPT 承载。

## 验收

1. company-007/e1 给出机读归因后转绿（引文落在保留的事实句/kept 单元）。
2. 语料族回归不回退；`verify_noise_verdicts`（I-E1/I-E2）继续通过。
3. 阈值变更留痕（先归因后调阈值，不反序）。

## 冻结影响

改 `clean.py` 噪声判定 ⇒ 影响 kept 单元集 ⇒ 触发全量重摄入 + 新冻结修订 `i0c-r4n`（或并入 F2 同批重摄入）。

## 不做

- 不先调阈值再验归因。
- 不改 `reasons` 形状、不改其他噪声规则（页眉/目录/页脚等阈值不在本票动）。