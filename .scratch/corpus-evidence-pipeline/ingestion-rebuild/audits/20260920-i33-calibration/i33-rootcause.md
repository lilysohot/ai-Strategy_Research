# I3-3 证据保留与坐标映射：分步根因取证与修复收口

只读取证（r39 事后，不改库/不改金标/不补证据）。分步先定根因、再启用修复。

## 1. 54 条缺失目标的根因精盘（Step 1）

对 54 条在 kept 正文（页级拼接）做**空白规约**包含，并用 `fetch_document` 全文做 LCS 交叉验证：

| 重分类 | 数量 | 含义 |
|---|---:|---|
| present_kept_bytes | 20 | quote 在 kept 页文本字节保留（原 14 块选择 + 原 6 坐标） |
| present_kept_norm_only | 14 | quote 空白规约后保留（版面换行/行内空格），字节不匹配 |
| present_doc_not_kept | 2 | 仅在非 kept（清洗剔除）单元出现：company-007/e1、company-008/a-1 |
| absent_in_extraction | 18 | **金标 quote 为改写/重建表述**，全文任意处（空白规约+全文 LCS）都不逐字出现 |

对 18 条做全文最长公共子串：全部为「内容大体在、字符序列不连续」（最长 LCS 6–194 / 归一quote长），
确证为**金标改写/重建说法**（如 company-001/e4「预测值67.74」正文疑为「预测值**为**67.74」；
macro-001/a-3、industry-003/a-3 为表格列/行跨结构重建）。
**检索/匹配/坐标层无法使这 20 条（18+2）命中，除非改金标或放宽证据语义——本收口不改金标。**

坐标前置事实：6 条公司-003（page:20）与 industry 表格目标的 reader 单元 **`cells=[]`、`element=null`**，
无结构化 cell 网格；row:/col: 表头标签无法从真实结构直接解析，需位置化表格解析器。按「宁缺坐标不贴错、
不伪造」原则，本收口**不接线**脆弱解析器，坐标目标统一记为**结构不可映射**。

## 2. 已启用修复（Step 2 评分器匹配口径）

`plugins/corpus/scoring.py` `_no_whitespace()` + `EvidenceTarget.matches()`：引文包含判定改为
**空白规约后的码位包含**，与金标 `exact()` 一致；非空白差异（千分位/大小写/全半角）照旧不命中。

对**原 OR 观测只读重打分**（不改检索、不补证据；差异仅评分口径）：

- 逐题 EvidencePass：company 1/8（未变）、industry 2/8（未变）、**macro 2/8 → 5/8**。
- 总命中目标 +7：company-002/e2、macro-005/e1、macro-006/e1·e2·a-3、macro-007/e1·e3。
- 负例 class（company-009/010、industry-009/010、macro-009/010）误报 6、伪造引用 6 **不受本口径影响**，属 OR 过宽的负例策略问题，不在本次证据修复范围内。

## 3. 未启用/如实记录（Step 3 坐标、Step 4 块选择）

- **坐标映射（6+industry 表格系）**：reader 无 cell 网格，结构映射置为不可达，不伪造、不改金标。
- **块选择（company-005/008、macro-003 跨单元 quote）**：quote 跨单元边界；已由空白规约覆盖到
  fetched 证据内的部分。整文档前 N 块候选已 100% 文档召回，块内跨单元重组属检索路径增强，
  不在本次收口强制启用。

## 4. 结论

- I3-3 **仍未通过**：company 1/8、industry 2/8、macro 5/8（门槛 19/20≥95%），并有 6 条负例误报。
- 本收口诚实交付：**匹配口径真实性提升（+7 目标）**；剩余 20 条缺失目标（18 改写重建 + 2 清洗剔除）
  与坐标目标如实登记为**检索/匹配层不可达**，**不改金标**。
- **M6 不放行**；I3-6 冻结/最终重验不因此轮放行。

## 可复验产物

- `i33-rootcause.json`（54 条逐条重分类 + 6 坐标结构 dump）
- `rescore_whitespace_norm.py`（只读重打分；对 scorer lineage 做内存层面确认，磁盘冻结件未动）
- 本 md；`plugins/corpus/scoring.py` 仅改 `matches()`/新增 `_no_whitespace()`；`tests/test_corpus_scoring.py` 新增空白规约用例。
- `diagnose_evidence.py`（r39 冻结脚本）**未就地改写**（遵循已关闭轮次产物不改写规则）。