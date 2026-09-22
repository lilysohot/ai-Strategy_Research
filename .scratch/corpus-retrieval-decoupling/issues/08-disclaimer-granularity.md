# 08 e1 `disclaimer_section` 判定粒度过宽

Status: completed（2026-09-22：U 具名裁决路径 (B)，`i0c-r4u` 落地后 e1 转绿；见文末收口记录）
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

## 2026-09-22 收口（U 具名裁决路径 (B)，`i0c-r4u` 落地）

**裁决**：U 具名指定路径 (B)——读取侧续接片段聚合，免重摄入。

**落地**（`audits/20260922-f3b-continuation-fragment/`，新冻结 `i0c-r4u` parent=`i0c-r4t`）：
`cross_boundary.aggregate_band_chunks`/`_merge_chunk` 扩展结构谓词 `stitch_continuation`（kept 单元句中截断 + 紧邻下一 ordinal 的 NOISE 尾片段以句末标点收尾即拼接补全句子 + 同页 ⇒ 按 (ordinal, unit_id) 保序聚合进块证据，内容哈希 fail-closed 同 F4；`_SENTENCE_TERMINAL`；`_BOUNDARY_UNITS_SQL` 增第三支候选）。谓词纯结构、不绑噪声类型、不按金标；三层扫描：裸放宽 132 处混入页眉/页脚紧邻，精化谓词全库仅 ord717/718 一处、误伤面=0。service.py 字节零改动（`search_bands` 既有接线直接生效，默认开）。

绑定：cross_boundary.py `85ee6be6`→`faa50936`、test_corpus_selection.py `1d0ecc29`→`b956fdc5`（+4 条 I-CONT-1 正/反向门）、freeze_validator→`d4ff1513`；manifest sha `4fb94875`。

**复验**（`f3b_replay.py`，0 model calls、只读 PG）：e1 off→on 转 green；目标级零回退且新增恰为 {company-007/e1}；EvidencePass 18/24→19/24（F4 基线不回退）；6 负例 retrieved_documents=0；选择不变（band 集相等、带宽 33≤49）；stitch=True 手工链与产品 `svc.search_bands` 逐字段一致。常驻测试 selection 34 passed（+4）、语料族 762 passed/12 skipped、ruff（CI 范围）/触及字节 pyright 绿、三门验证器 exit 0。r4v 复验不回退（21/24）。

**纪律**：不 commit、不 publish、不重摄入、不写库。