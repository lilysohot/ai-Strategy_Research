# E6 缺口预筛（非裁决）

> Mechanical pre-screen only. No decision is recorded and no human-gap-review is written; every direction here is a reading aid and a reviewer still signs the packet.

## 范围

- 被阻断材料：**9** 份；被阻断目标：**38** 项。
- 证据来源：冻结门禁 `e6-holdout-build.json`、`e6-data-delivery-holdout.json`，以及隔离库 `e6_holdout_corpus`（只读事务）。

## 方法

对每个被阻断目标，取其 expected_quote，做 NFKC+去空白归一化后，在冻结 build 的 corpus_units 文本（kept 与全量两套）中做字面比对：整条引文 / 按句切分的片段是否已在已提取文本中，以及命中的证据页是否落在门禁 gap_regions 标记的页上。

## 已知局限（务必连读）

- 只比对『引文是否已被提取』，不重跑 corpus_search / fetch_plan / corpus_fetch；被阻断 build 未发布，无法做真实投递验证。
- 引文存在 ≠ 检索可达：目标仍可能因分块或检索未命中而失败。
- 方向列（leaning-*）由字面比对机械得出，不是裁决、不带签名。

## 预筛分布

| 预筛方向 | 目标数 |
|---|---:|
| `leaning-acknowledge` | 28 |
| `leaning-re-extract` | 3 |
| `needs-human` | 7 |

| 结果 | 目标数 | 含义 |
|---|---:|---|
| `absent` | 3 | 未见提取：引文完全不在已提取文本中 |
| `benign_overlap` | 28 | 轻微交集：引文已完整提取，证据页仅有小图片区域缺口 |
| `overlap` | 7 | 实质交集：引文已完整提取，但证据页带可能遮挡的缺口 |

## 1. `holdout-industry-003`（industry）

- `build_id`：`907957c865f6b551f70e6254a270a29b2baab31adf98d24c3250d964278432db`
- 缺口页：1（image_region_small）, 2（image_region_small）, 3（image_region_small, table_lines_without_extraction）, 4（image_region_small）, 5（image_region_small）, 6（image_region_small）, 7（image_region_small）, 8（image_region_small, table_lines_without_extraction）, 9（image_region_small）, 10（image_region_small）, 11（image_region_small, table_lines_without_extraction）, 12（image_region_small）, 13（image_region_small）, 14（image_region_small）, 15（image_region_small）, 16（image_region_small, table_lines_without_extraction）, 17（image_region_small）, 18（image_region_small, table_lines_without_extraction）, 19（image_region_small, table_lines_without_extraction）, 20（image_region_small）, 21（image_region_small）, 22（image_region_small）
- 已提取：units 1092，状态 {'kept': 1004, 'noise': 88}
- 本材料分布：`absent` 1, `benign_overlap` 3

| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |
|---|---|---|---|---:|---|---|---|
| `c1ddcd8a-coalprice` | required | `leaning-acknowledge` | `benign_overlap` | 2/2 | 1 | 1 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `c1ddcd8a-summarytable` | supplementary | `leaning-re-extract` | `absent` | 0/1 | — | — | 引文与其所有片段均未出现在已提取文本中；相关缺口页：page 1, page 2, page 3, page 4, page 5, page 6, page 7, page 8, page 9, page 10, page 11, page 12, page 13, page 14, page 15, page 16, page 17, page 18, page 19, page 20, page 21, page 22 |
| `c1ddcd8a-realestate` | supplementary | `leaning-acknowledge` | `benign_overlap` | 2/2 | 1, 9 | 1, 9 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `c1ddcd8a-invest` | supplementary | `leaning-acknowledge` | `benign_overlap` | 2/2 | 1, 20 | 1, 20 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |

## 2. `holdout-industry-004`（industry）

- `build_id`：`590bb1199568dd8a78083d2b6dc856c7b3b9cff32a2b8a811c34a3820ea23814`
- 缺口页：1（image_region_small, image_region_unreadable）, 2（image_region_small, image_region_unreadable）, 3（image_region_small, image_region_unreadable）, 4（image_region_small, image_region_unreadable, table_lines_without_extraction）, 5（image_region_small, image_region_unreadable, table_lines_without_extraction）, 6（image_region_small, image_region_unreadable, table_lines_without_extraction）, 7（image_region_small, image_region_unreadable）, 8（image_region_small, image_region_unreadable）, 9（image_region_small, image_region_unreadable）, 10（image_region_small, image_region_unreadable）, 11（image_region_small, image_region_unreadable）, 12（image_region_small, image_region_unreadable）, 13（image_region_small, image_region_unreadable, table_lines_without_extraction）, 14（image_region_small, image_region_unreadable）, 15（image_region_small, image_region_unreadable）, 16（image_region_small, image_region_unreadable, table_lines_without_extraction）, 17（image_region_small, image_region_unreadable, table_lines_without_extraction）, 18（image_region_small, image_region_unreadable, table_lines_without_extraction）, 19（image_region_small, image_region_unreadable, table_lines_without_extraction）, 20（image_region_small, image_region_unreadable）, 21（image_region_small, image_region_unreadable）, 22（image_region_small, image_region_unreadable）, 23（image_region_small, image_region_unreadable）, 24（image_region_small, image_region_unreadable）, 25（image_region_small, image_region_unreadable）, 26（image_region_small, image_region_unreadable）, 27（image_region_small, image_region_unreadable）
- 已提取：units 1153，状态 {'kept': 1102, 'noise': 51}
- 本材料分布：`overlap` 4

| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |
|---|---|---|---|---:|---|---|---|
| `b7e932c8-index` | required | `needs-human` | `overlap` | 2/2 | 2, 4 | 2, 4 | 证据页带缺口：page 2（image_region_small, image_region_unreadable）, page 4（image_region_small, image_region_unreadable, table_lines_without_extraction） |
| `b7e932c8-industry` | required | `needs-human` | `overlap` | 2/2 | 2, 6 | 2, 6 | 证据页带缺口：page 2（image_region_small, image_region_unreadable）, page 6（image_region_small, image_region_unreadable, table_lines_without_extraction） |
| `b7e932c8-pmi` | supplementary | `needs-human` | `overlap` | 2/2 | 3 | 3 | 证据页带缺口：page 3（image_region_small, image_region_unreadable） |
| `b7e932c8-eptable` | supplementary | `needs-human` | `overlap` | 1/1 | 7 | 7 | 证据页带缺口：page 7（image_region_small, image_region_unreadable） |

## 3. `holdout-industry-006`（industry）

- `build_id`：`00b99a5809fc5dd51f29588f10778e90f8a579ef68cf2bfe4a3710ba926e4af7`
- 缺口页：1（image_region_small）, 2（image_region_small）, 3（image_region_small, table_lines_without_extraction）, 4（image_region_small）, 5（image_region_small）, 6（image_region_small, image_region_unreadable）, 7（image_region_small）, 8（image_region_small）, 9（image_region_small）, 10（image_region_small）, 11（image_region_small）, 12（image_region_small）, 13（image_region_small）, 14（image_region_small, table_lines_without_extraction）, 15（image_region_small）, 16（image_region_small）, 17（image_region_small）, 18（image_region_small）, 19（image_region_small）, 20（image_region_small）
- 已提取：units 469，状态 {'kept': 361, 'noise': 108}
- 本材料分布：`benign_overlap` 3, `overlap` 2

| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |
|---|---|---|---|---:|---|---|---|
| `f86c6d2c-cxo-h1` | required | `needs-human` | `overlap` | 2/2 | 3 | 3 | 证据页带缺口：page 3（image_region_small, table_lines_without_extraction） |
| `f86c6d2c-wuqi-order` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 5 | 5 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `f86c6d2c-medamt` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1, 15 | 1, 15 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `f86c6d2c-cxotable` | supplementary | `leaning-acknowledge` | `benign_overlap` | 1/1 | 4 | 4 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `f86c6d2c-glp1` | supplementary | `needs-human` | `overlap` | 1/1 | 6 | 6 | 证据页带缺口：page 6（image_region_small, image_region_unreadable） |

## 4. `holdout-industry-007`（industry）

- `build_id`：`c9624c5c39909971c39ccd4a8017ab1fd7eaa3626ce8b4b9a8edf893d8bee593`
- 缺口页：1（image_region_small）, 2（image_region_small）, 3（image_region_small）, 4（image_region_small）, 5（image_region_small）, 6（image_region_small, table_lines_without_extraction）, 7（image_region_small, table_lines_without_extraction）, 8（image_region_small）, 9（image_region_small）, 10（image_region_small）, 11（image_region_small）, 12（image_region_small）, 13（image_region_small）, 14（image_region_small）
- 已提取：units 681，状态 {'kept': 630, 'noise': 51}
- 本材料分布：`benign_overlap` 4

| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |
|---|---|---|---|---:|---|---|---|
| `a91d95c7-hbm` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1 | 1 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `a91d95c7-bytedance` | required | `leaning-acknowledge` | `benign_overlap` | 2/2 | 1, 11 | 1, 11 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `a91d95c7-hbmprice` | required | `leaning-acknowledge` | `benign_overlap` | 2/2 | 8 | 8 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `a91d95c7-cxmt` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1 | 1 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |

## 5. `holdout-macro-008`（macro）

- `build_id`：`313426724dd6b55b978887cc06818f78ba66aa445c37b95c8eeaff554fc0e6e8`
- 缺口页：1（image_region_small）, 2（image_region_small）, 3（image_region_small）, 4（image_region_small, table_lines_without_extraction）, 5（image_region_small, table_lines_without_extraction）, 6（image_region_small）, 7（image_region_small）, 8（image_region_small）, 9（image_region_small, table_lines_without_extraction）, 10（image_region_small）, 11（image_region_small, image_region_unreadable）, 12（image_region_small）, 13（image_region_small）, 14（image_region_small, table_lines_without_extraction）, 15（image_region_small, table_lines_without_extraction）, 16（image_region_small）, 17（image_region_small）, 18（image_region_small）
- 已提取：units 1432，状态 {'kept': 1304, 'noise': 128}
- 本材料分布：`benign_overlap` 5

| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |
|---|---|---|---|---:|---|---|---|
| `5e305376-nonfarm` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1 | 1 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `5e305376-fedrate` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1 | 1 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `5e305376-oil` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1 | 1 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `5e305376-dxy` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1 | 1 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `5e305376-gdpnow` | supplementary | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1 | 1 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |

## 6. `holdout-macro-009`（macro）

- `build_id`：`45383590029c0b354f7aeb28a0021ccb789bc852159fed3095ce6a5754740538`
- 缺口页：1（image_region_small）, 2（image_region_small）, 3（image_region_small）, 4（image_region_small）, 5（image_region_small）, 6（image_region_small）, 7（image_region_small）, 8（image_region_small）, 9（image_region_small, image_region_unreadable）, 10（image_region_small）, 11（image_region_small）
- 已提取：units 176，状态 {'kept': 146, 'noise': 30}
- 本材料分布：`benign_overlap` 4

| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |
|---|---|---|---|---:|---|---|---|
| `f7f65d7e-payroll` | required | `leaning-acknowledge` | `benign_overlap` | 3/3 | 7 | 7 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `f7f65d7e-cme` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1, 8 | 1, 8 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `f7f65d7e-alloc` | required | `leaning-acknowledge` | `benign_overlap` | 2/2 | 1, 8 | 1, 8 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `f7f65d7e-risk` | supplementary | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1, 10 | 1, 10 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |

## 7. `holdout-macro-010`（macro）

- `build_id`：`fc7ab34ae8cc16e8f805096db5fb6ab7d2ec221e410a335b4d6032d4278a8519`
- 缺口页：1（image_region_small）, 2（image_region_small）, 3（image_region_small）, 4（image_region_small）, 5（image_region_small）, 6（image_region_small）, 7（image_region_small）, 8（image_region_small, table_lines_without_extraction）, 9（image_region_small）, 10（image_region_small）, 11（image_region_small）
- 已提取：units 481，状态 {'kept': 451, 'noise': 30}
- 本材料分布：`absent` 1, `benign_overlap` 3

| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |
|---|---|---|---|---:|---|---|---|
| `d179b615-hikerate` | required | `leaning-acknowledge` | `benign_overlap` | 3/3 | 1, 4 | 1, 4 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `d179b615-passive` | required | `leaning-acknowledge` | `benign_overlap` | 3/3 | 1, 4 | 1, 4 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `d179b615-chart3` | required | `leaning-re-extract` | `absent` | 0/1 | — | — | 引文与其所有片段均未出现在已提取文本中；相关缺口页：page 1, page 2, page 3, page 4, page 5, page 6, page 7, page 8, page 9, page 10, page 11 |
| `d179b615-goldoil` | supplementary | `leaning-acknowledge` | `benign_overlap` | 1/1 | 7 | 7 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |

## 8. `holdout-macro-011`（macro）

- `build_id`：`ffb0ccd22615b21f3a4e4f22967fb4c45ed8f25ae84bc111777d0938e0efd5f4`
- 缺口页：1（image_region_small）, 2（image_region_small）, 3（image_region_small）, 4（image_region_small）, 5（image_region_small）, 6（image_region_small）, 7（image_region_small）, 8（image_region_small）, 9（image_region_small）, 10（image_region_small）, 11（image_region_small, table_lines_without_extraction）, 12（image_region_small）, 13（image_region_small）
- 已提取：units 232，状态 {'kept': 231, 'noise': 1}
- 本材料分布：`benign_overlap` 3, `overlap` 1

| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |
|---|---|---|---|---:|---|---|---|
| `2f8aa709-hike` | required | `leaning-acknowledge` | `benign_overlap` | 3/3 | 4 | 4 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `2f8aa709-oil` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 8 | 8 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `2f8aa709-alloc` | required | `needs-human` | `overlap` | 4/4 | 1, 11 | 1, 11 | 证据页带缺口：page 1（image_region_small）, page 11（image_region_small, table_lines_without_extraction） |
| `2f8aa709-fedtable` | supplementary | `leaning-acknowledge` | `benign_overlap` | 2/2 | 4 | 4 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |

## 9. `holdout-macro-012`（macro）

- `build_id`：`fa066c5a178c02128b5058d62ccaff442fa3004bd6d43e1189f6f75257900209`
- 缺口页：1（image_region_small）, 2（image_region_small）, 3（image_region_small）, 4（image_region_small）, 5（image_region_small）, 6（image_region_small）, 7（image_region_small）, 8（image_region_small, table_lines_without_extraction）, 9（image_region_small）, 10（image_region_small）, 11（image_region_small）
- 已提取：units 278，状态 {'kept': 244, 'noise': 34}
- 本材料分布：`absent` 1, `benign_overlap` 3

| target_id | role | 预筛方向 | 结果 | 引文覆盖 | 证据页 | 交集缺口页 | 说明 |
|---|---|---|---|---:|---|---|---|
| `f3b28791-rotation` | required | `leaning-acknowledge` | `benign_overlap` | 2/2 | 1, 3 | 1, 3 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `f3b28791-fedwatch` | required | `leaning-acknowledge` | `benign_overlap` | 2/2 | 6 | 6 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |
| `f3b28791-table1` | required | `leaning-re-extract` | `absent` | 0/1 | — | — | 引文与其所有片段均未出现在已提取文本中；相关缺口页：page 1, page 2, page 3, page 4, page 5, page 6, page 7, page 8, page 9, page 10, page 11 |
| `f3b28791-regression` | required | `leaning-acknowledge` | `benign_overlap` | 1/1 | 1, 9 | 1, 9 | 证据页仅有 image_region_small：小图片区域不覆盖正文/表格行 |

## 重申

本预筛不构成裁决：不改发布门、不写 `human-gap-review`、不代签。

- `leaning-acknowledge`：引文整条已落在 kept 单元中，证据页最多只有 `image_region_small`（小图片区域，不覆盖正文/表格行）。仍需人工签署。
- `needs-human`：引文虽已提取，但证据页带 `image_region_unreadable` 或 `table_lines_without_extraction`，缺口与证据同页，须逐页对照原稿判断。
- `leaning-re-extract`：引文及其片段均未出现在已提取文本中，缺口疑似正压在这条证据上。

三者都不是终局：是否 `acknowledged` / `re-extract` / `reject` 由人工裁决，本轮不写任何裁决行。
