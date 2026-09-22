# 08 e1 `disclaimer_section` 判定粒度过宽

Status: in-progress（2026-09-22 复验：验收 1 未达，见文末）
Type: task
Depends: S5（已完成，机读判定已就位）
Layer: clean
Bound-byte impact: **是**（`plugins/corpus/preparation/clean.py`）
Reingest: **是**（已于 2026-09-22 随 B2 真库复验全量重建 8 builds；F3 单元级判定已落到语料）
Resolved: 2026-09-21（代码冻结 `i0c-r4p`；**验收 1「e1 转绿」2026-09-22 复验仍未达**）

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

## 2026-09-22 B3 复验（验收 1 未达；重摄入已完成）

**执行**：`audits/20260921-f3-disclaimer-granularity/` —— `f3_replay.py`（同口径 79 目标回放，band 选择 +
产品 `search_bands` 复核，0 model calls、只读 PG）+ `f3_fragment_scan.py`（全库结构扫描）；产物
`f3-summary.json` / `f3-funnel-targets.json` / `f3-report.md` / `f3-fragment-scan.json`。

**结论：重摄入不构成充分条件，e1 仍未转绿。**

| 观测 | 值 |
|---|---|
| funnel S0/S1/S2/S3/S4 | 77 / 66 / 60 / 59 / 50（与 F2 基线逐层一致，F3+重摄入零位移） |
| `company-007 e1` 逐层 | S0=F S1=F S2=F S3=F S4=F，bucket=`not_in_doc_unreachable` |
| ord717（事实句前半） | `kept`（F3 生效） |
| ord718（尾片段「份。」） | `noise` / `disclaimer_section`，**不在任何块内** |
| 含 ord717 的块 | `unit:0709-0715,0717`（body）；`has_tail_fragment=false` |
| 该块可否召回 / 文档进 top-5 | 是 / 是 |
| 引文在该块文本内 | **否**（块文本止于「4.06%的股」） |
| 接回 ord718 后引文逐字可承载 | **是** |
| 全库同构样本（kept + disclaimer 尾片段） | **1**（仅本处） |

**根因（精确）**：事实句被版面切成两单元，F3 的判定粒度是**单元**：
含数字事实的 ord717 降 KEPT，而纯尾片段 ord718 仍 NOISE；块装配只取 kept 单元 ⇒
引文在句中断开，逐字包含判定（`EvidenceTarget.matches`，空白规约后码位包含）必然失败。
`matched_tokens`（4.06%）不影响判定——判据是整条 `quote` 的逐字包含。

**修复路径（须 U 裁决，未擅自实施）**：

| 路径 | 动作 | 代价 |
|---|---|---|
| A | `clean.py` 粒度扩到**句跨单元**（同一句的全部布局单元同生命周期） | 改被绑字节 + **再重摄入** + 新冻结修订 + 粒度具名签认 |
| B | 读取侧**续接片段聚合**（同页 + ordinal 相邻 + 前单元未以句末标点结束的 `disclaimer_section` 片段并进块证据） | 免重摄入；需新冻结修订；与 F4 `cross_boundary` 同类，但多一条聚合谓词 |
| C | 登记不修（e1 恒 `not_in_doc_unreachable`，M6 仍可被其它目标拖住） | 零代价，e1 永久不可达 |

**未做（纪律）**：未改 `clean.py`/`service.py`/`cross_boundary.py` 任何字节；未重摄入；未写库；未 publish；未建冻结修订。