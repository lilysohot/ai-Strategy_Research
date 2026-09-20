# I3-5 PG kept 文本取证（reader-pdf-5，对准数复跑）

- 生成：2026-09-20T20:35:48+08:00；口径：从 PG 读新 build 的 kept 单元按页码拼接
- 基线：I3-3 的 `exact_quote_not_in_kept_page_text` = 34（reader-pdf-2，全部 miss）

## 命中 32/34（kept 页内），另 32 命中于全文任意 kept 页

| 来源 | 目标数 | kept页命中 | 全文任页命中 |
|---|---|---|---|
| 6f14cc145b79 | 8 | 6 | 6 |
| dddc7cd0cb74 | 4 | 4 | 4 |
| 174b64628f35 | 2 | 2 | 2 |
| f8e316969b7c | 5 | 5 | 5 |
| 793b39673d31 | 9 | 9 | 9 |
| cc03f55bc5a2 | 6 | 6 | 6 |

## 未命中（kept 页内逐字）

- company-007 e1 p7
- company-008 a-1 p1

- 茅台 company-001 p1 连续引号：True
- 说明：kept 页内未命中未必代表引号缺失，可能跨页/换行/Tab 差异；见 target_rows 明细。
