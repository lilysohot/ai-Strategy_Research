# I3-3 议题 A 实测：连续块区间取回（band interval retrieval）

- 生成：2026-09-20T23:05:03+08:00；类型：诊断（**非冻结回归**）
- scorer：工作树空白规约版 `f61573d71b54`（未冻结未采纳）；评分资产冻结字节已核验
- corpus：8 份 active builds（reader-pdf-5 重摄入）
- 带参数：G=1（空隙容忍）/ K=1（两端扩展）/ 带上限=8
- 语义边界：不调 cap 值（8=带数）；带由 OR 词元命中池形成；不做整篇文档取回；不按金标词/页/行列补取

## 逐层对比（有答案题 EvidencePass + 负例误报）

| 层 | company | industry | macro | 合计 | 负例误报 |
|---|---|---|---|---|---|
| base（前8块·页级） | 3/8 | 4/8 | 6/8 | 13/24 | 0 |
| band（带区间取回·带数8） | 5/8 | 4/8 | 8/8 | 17/24 | 0 |

## 议题 A：11 条带覆盖可行性（主口径 G=1/K=1）

| 目标 | 引文长 | cover | 池内块 | coverable | 带排名 | 进带数8 | 拼接含引文 | band层匹配 |
|---|---|---:|---:|---|---|---|---|---|
| company-004 e2 | 159 | [28, 32] | 112 | True | 3 | True | True | True |
| company-004 a-2 | 159 | [28, 32] | 112 | True | 3 | True | True | True |
| company-004 a-3 | 159 | [28, 32] | 112 | True | 3 | True | True | True |
| company-005 e2 | 61 | [71, 72] | 101 | True | 2 | True | True | True |
| company-005 e3 | 108 | [76, 78] | 101 | True | 2 | True | True | True |
| company-008 a-2 | 42 | [2, 3] | 148 | True | 7 | True | True | True |
| company-008 a-3 | 73 | [37, 39] | 148 | True | 3 | True | True | True |
| company-008 a-5 | 73 | [37, 39] | 148 | True | 3 | True | True | True |
| macro-002 e4 | 648 | [5, 6] | 96 | True | 1 | True | True | True |
| macro-003 a-2 | 648 | [5, 6] | 69 | True | 1 | True | True | True |
| macro-003 a-4 | 648 | [5, 6] | 69 | True | 1 | True | True | True |

## 敏感性扫描（gap, expand）→ 进带数 8 的目标数

- (G=1, K=1)：11/11 进带数 8
- (G=1, K=2)：11/11 进带数 8
- (G=2, K=2)：11/11 进带数 8
- (G=2, K=3)：11/11 进带数 8

## 负例（S4 窄检索）

- company-009：命中文档 0（期望 0）
- company-010：命中文档 0（期望 0）
- industry-009：命中文档 0（期望 0）
- industry-010：命中文档 0（期望 0）
- macro-009：命中文档 0（期望 0）
- macro-010：命中文档 0（期望 0）
