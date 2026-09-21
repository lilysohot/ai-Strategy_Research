# 票 05 目标级归因：清洗判定依据可机读（S5）

日期：2026-09-21
目录：`audits/20260921-s5-noise-verdict/`
产物：`s5_verdict.py`（重放脚本，只读 PG + 0 model calls）、`s5-summary.json`（write-once）
方案：`.scratch/corpus-retrieval-decoupling/spec.md` §7.5（票 05）/ §8.1（I-E1/I-E2）

## 1. 本票做了什么

在 `plugins/corpus/preparation/clean.py` 落地**机读判定依据**（不改 `reasons` 形状、不调任何阈值）：

- 新增 `NoiseVerdict(code, rule, observed, threshold)` 与 `CleanRegion.verdicts`；
- 各 NOISE 分支填充依据：页眉/页脚带（`banded_repeated_geometric`，observed=重复页数/页/bbox/带边界，
  threshold=`_REPEAT_MIN_PAGES`/`_BAND_RATIO`）、目录（`exact_toc_heading`/`dot_leader_lines`）、
  免责声明（`disclaimer_heading_exact`/`disclaimer_section_after_heading`/`disclaimer_prefix_paragraph`）、
  分析师名单（`analyst_roster_lines`）、合成缺口（`synthetic_gap_noise`，当前仅 `image_region_small`）；
- `verify_noise_verdicts` 构造后 fail-closed 校验 I-E1（NOISE 区 verdicts 非空、每条 code ∈ reasons）
  与 I-E2（observed 非空含数值/坐标）；
- 判定语义：NOISE 区只保留已触发判定；KEPT 区可含"评估过但未越阈值"的近似命中
  （如页眉只重复 2 页 → `observed["repeat_pages"] == 2`）。

常驻测试（`tests/test_corpus_preparation_clean.py` 新增 3 条）：I-E1/I-E2 全规则遍历、
`verify_noise_verdicts` 拒绝破坏、2 页页眉反例。`tests/test_corpus_*.py` = **731 passed / 12 skipped**（基线不回退）。

## 2. 重放方法

对 §10.4 已裁定 i37 成立的两条目标（company-007/e1、company-008/a-1），在当前活动语料
（index-4-zhcfg-2，build `58735cff…`）上：

1. 取目标 build 全量单元（`corpus_units`，含 raw_text/kind/page/bbox）；
2. 以 **reader 态**重建 `CandidateUnit`（status=KEPT、reasons=()）重放 `clean_reader_result`——
   噪声判定是 (raw_text, kind, page, bbox) 的纯函数，重放即复现当时判定依据；
3. 对每条目标定位引文片段命中的单元，输出重放 verdicts 与存储 status/reasons 的 `status_match` 比对。

## 3. e1：`disclaimer_section` 规则过宽（粒度）

命中单元：ord=717，p7，整段分析师声明（193 字）。重放判定：

```json
{
  "code": "disclaimer_section",
  "rule": "disclaimer_section_after_heading",
  "observed": {"origin_ordinal": "716", "origin_heading": "分析师声明"},
  "threshold": {"disclaimer_headings": "['免责声明', '免责条款', '分析师声明', '分析师申明', '评级说明', '重要声明']"}
}
```

- `status_match=true`：重放与入库一致（noise）。
- 机理：`disclaimer_section` 按「免责声明/评级说明标题 → 下一标题」**整段剔除**。
  该段确为分析师声明（免责声明节），但**同一单元内含实质事实句**「华创云信 4.06% 持股」。
- **判定：规则过宽（粒度）**。lever 是 `disclaimer_section` 的判定粒度（整段 → 事实句保留/子句粒度），
  与 §10.4 裁定一致。调阈值不解决问题（问题不在命中与否，而在剔除单位是"整段"）。

## 4. a-1：页眉本就该剔，损失归引文边界（另立议题）

命中单元：7 个（ord=5/100/123/617/640/689/706，p1–p7），全部 `status_match=true`，均为
`header_repeated_geometric`（p1 另带 reader 原因 `heading_by_font_size`）。代表性 verdict：

```json
{
  "code": "header_repeated_geometric",
  "rule": "banded_repeated_geometric",
  "observed": {"repeat_pages": "7", "page": "7",
               "bbox": "(417.5, 41.9, 564.2, 51.9)",
               "top_bound": "133.8", "bottom_bound": "715.8"},
  "threshold": {"min_pages": "3", "band_ratio": "0.12"}
}
```

- `observed.repeat_pages = 7 ≥ threshold.min_pages = 3` 且位于页顶带（`bbox[3] ≤ top_bound`）。
- **判定：规则按定义正确触发（页眉本就该剔）**，不是规则过宽。
- 引文前半「贵州茅台（600519）2026 年中报点评」在该 NOISE 表头，后半「强推（维持）」在 kept 单元
  ord=6 p1 ⇒ **引文横跨 NOISE/kept 边界**。损失归**表归属/引文粒度**，另立议题（§13.1 note），本票不处理。

## 5. 结论与价值口径

- e1 = 规则过宽（`disclaimer_section` 粒度）；a-1 = 本就该剔（损失为引文边界问题，另立议题）。
- **本票只加机读记账，不提升 EvidencePass**；价值在归因能力与后续阈值/粒度立项的依据
  （例如：把 `disclaimer_section` 从"整段"收窄到"声明子句/事实句保留"时，e1 的判定可直接用 verdict 复核）。
- 不调任何噪声阈值（调阈值须单独立项 + 具名签认）。
