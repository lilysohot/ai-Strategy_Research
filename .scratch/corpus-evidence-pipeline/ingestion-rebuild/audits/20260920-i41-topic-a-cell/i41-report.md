# I3-3 议题 A 收紧版 + S2 坐标投影：带跨度上限（方案 C）+ cell 网格 row:/col:

- 生成：2026-09-20T23:47:01+08:00；类型：诊断（**非冻结回归**）
- scorer：工作树空白规约版 `f61573d71b54`（未冻结未采纳）；评分资产冻结字节已核验
- corpus：8 份 active builds（reader-pdf-5 重摄入）
- 带参数：G=1（空隙容忍）/ K=1（两端扩展）/ 带上限=8
- **跨度上限声明：方案 C（带内池块数上限 POOL_CAP=24）**；超限簇按池块锚拆子带
- 可证带宽上界：W_max = (POOL_CAP-1)*(G+1)+1+2*K = **49 块**（G=1/K=1）
- 体积实测：最大带宽 33 ≤ 49（满足）
- 语义边界：不调 cap 值（8=带数）；带由 OR 词元命中池形成；不做整篇文档取回；不按金标词/页/行列补取
- S2 坐标投影：仅对**已选带内** chunk 的 table_row 单元派生 row:/col: 并发射 cell 证据（不改变选择）
- 单变量：负例与有答案题同一 OR 检索管线（不混入 S4 窄检索）

## 逐层对比（有答案题 EvidencePass + 负例误报）

| 层 | company | industry | macro | 合计 | 负例误报 |
|---|---|---|---|---|---|
| base（前8块·页级） | 3/8 | 4/8 | 6/8 | 13/24 | 6 |
| band（带区间取回·带数8·POOL_CAP=24） | 5/8 | 4/8 | 8/8 | 17/24 | 6 |
| band+S2（+cell 网格 row:/col:） | 6/8 | 5/8 | 8/8 | 19/24 | 6 |

## S2 坐标投影（row:/col: 目标）

- 总数：13；转绿：11；仍失败：2

- company-003 e1 ['page:20', 'row:每股收益', 'col:2026E'] → matched（layer=band_s2）
- company-003 e2 ['page:20', 'row:经营活动现金流', 'col:2026E'] → matched（layer=band_s2）
- company-003 e3 ['page:20', 'row:每股收益', 'col:2027E'] → matched（layer=band_s2）
- company-003 e4 ['page:20', 'row:经营活动现金流', 'col:2027E'] → matched（layer=band_s2）
- company-003 e5 ['page:20', 'row:每股收益', 'col:2028E'] → matched（layer=band_s2）
- company-003 e6 ['page:20', 'row:经营活动现金流', 'col:2028E'] → matched（layer=band_s2）
- industry-001 e1 ['page:10', 'row:纯碱', 'col:价格分位'] → matched（layer=band_s2）
- industry-001 e2 ['page:10', 'row:纯碱', 'col:价差分位'] → matched（layer=band_s2）
- industry-001 e3 ['page:10', 'row:纯碱', 'col:开工率'] → matched（layer=band_s2）
- industry-002 e1 ['page:10', 'row:R32', 'col:价格分位'] → matched（layer=band_s2）
- industry-002 e2 ['page:10', 'row:R32', 'col:2026E产能（配额）'] → still_fail
- industry-003 e1 ['page:10', 'row:尿素', 'col:开工率'] → matched（layer=band_s2）
- industry-003 e2 ['page:10', 'row:尿素', 'col:2026E产能'] → still_fail

仍失败的 row:/col: 目标（金标合成列标签，cell 网格无法派生等义 token）：

- industry-002 e2 ['page:10', 'row:R32', 'col:2026E产能（配额）']
- industry-003 e2 ['page:10', 'row:尿素', 'col:2026E产能']

## 议题 A：11 条带覆盖可行性（主口径 G=1/K=1，含 POOL_CAP=24）

| 目标 | 引文长 | cover | 池内块 | coverable | 带排名 | cover带宽 | 进带数8 | 拼接含引文 | band_s2层匹配 |
|---|---|---:|---:|---|---|---:|---|---|---|
| company-004 e2 | 159 | [28, 32] | 112 | True | 3 | 19 | True | True | True |
| company-004 a-2 | 159 | [28, 32] | 112 | True | 3 | 19 | True | True | True |
| company-004 a-3 | 159 | [28, 32] | 112 | True | 3 | 19 | True | True | True |
| company-005 e2 | 61 | [71, 72] | 101 | True | 3 | 33 | True | True | True |
| company-005 e3 | 108 | [76, 78] | 101 | True | 3 | 33 | True | True | True |
| company-008 a-2 | 42 | [2, 3] | 148 | True | 8 | 8 | True | True | True |
| company-008 a-3 | 73 | [37, 39] | 148 | True | 4 | 10 | True | True | True |
| company-008 a-5 | 73 | [37, 39] | 148 | True | 4 | 10 | True | True | True |
| macro-002 e4 | 648 | [5, 6] | 96 | True | 1 | 8 | True | True | True |
| macro-003 a-2 | 648 | [5, 6] | 69 | True | 1 | 8 | True | True | True |
| macro-003 a-4 | 648 | [5, 6] | 69 | True | 1 | 8 | True | True | True |

## 敏感性扫描（gap, expand）+ POOL_CAP=24 → 进带数 8 的目标数

- (G=1, K=1)：11/11 进带数 8；可证带宽上界 49
- (G=1, K=2)：11/11 进带数 8；可证带宽上界 51
- (G=2, K=2)：11/11 进带数 8；可证带宽上界 74
- (G=2, K=3)：11/11 进带数 8；可证带宽上界 76

## 体积上界（方案 C，POOL_CAP=24，G=1/K=1）

- 可证带宽上界：**49 块/带**（推导：每带 ≤24 池块，相邻池块间隔 ≤G+1=2，加两端扩展 K=1）
- 实测最大带宽：**33 ≤ 49**
- 聚合上界：每文档选中块数 ≤ min(n, 8×49=392)
- 实测最差聚合（占比）：company-001 → 文档 48c05895798b… n=7 选中 7 块（100.0%）
- 实测最大聚合（绝对块数）：industry-004 → 文档 174b64628f35… n=284 选中 196 块（69.0%）

### 用户点名文档聚合对比（i39 未收紧 / 收紧后同文档）

| 题 | 文档块数 | i39 聚合占比 | 收紧后 union | 收紧后占比 |
|---|---|---:|---:|---:|
| company-004 | 197 | 52%（i39 未收紧） | 103 | 52.3% |
| industry-001 | 284 | 70%（i39 未收紧） | 125 | 44.0% |

## 负例（单变量：OR 检索路径）

- company-009：OR 检索命中文档 5（期望 0） —— 误报
- company-010：OR 检索命中文档 5（期望 0） —— 误报
- industry-009：OR 检索命中文档 5（期望 0） —— 误报
- industry-010：OR 检索命中文档 5（期望 0） —— 误报
- macro-009：OR 检索命中文档 5（期望 0） —— 误报
- macro-010：OR 检索命中文档 5（期望 0） —— 误报
