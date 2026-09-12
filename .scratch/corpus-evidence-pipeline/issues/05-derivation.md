# 05 可计算投影与推导

Status: ready-for-agent
Execution: completed
Blocked by: 03, 04

计算必须声明公式、输入事实 ID、原始/规范单位、期间、来源版本与状态；检查主体/口径/期间可比性和除零。输出财务增长、比率、勾稽结果及拒绝原因。

## Comments

2026-09-12：7 个公式实现，输出绑定 run_id、fact IDs、Decimal 输入、期间与公式版本。跨主体/单位/口径/版本、重复输入及反向期间被拒；真实样本 7 项复算通过，两项勾稽残差为 0。预测结果显式 source_forecast，不伪装已实现业绩。
