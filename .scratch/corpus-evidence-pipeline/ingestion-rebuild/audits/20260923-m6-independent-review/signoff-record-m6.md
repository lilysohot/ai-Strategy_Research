# M6 放行签认记录（U 具名签认）

| 项 | 内容 |
|---|---|
| 状态 | **已签认（signed）** · reviewer 具名入链 i0c-r5c |
| 范围 | M6 最终版本放行（I3-6 冻结版本 i0c-r4z × I3-7 最终重验 × 独立复核） |
| 复核结论 | 通过（[review.md](review.md)：独立重证零反例） |
| 签认人 | **xyl** |
| 签认时间 | 2026-09-23 |

## 签认决定

1. **M6 放行**：认可 M6 独立复核结论与 I3-7 全部结果。M6 放行三要件——I3-7 通过、
   独立复核通过、U 具名签认——全部达成。
2. **abstain=on 正例误拒（24/24）处置：接受为已知限制**。关闭 S1「正例不误拒」设计宣称并
   登记；负例 6/6 冻结口径与评分层 24/24 不受影响；日后如需恢复该宣称，另立整改任务走
   版本冻结 + 重验。

## 签认所依据的证据

- [I3-7 最终重验](../20260923-i37-final-reverify/README.md)：重建 8/8 published+active、
  评分 14 门全绿、测试 9 门全绿、legacy 同口径全过；
- [M6 独立复核](review.md)：三门验证器 exit 0；r5b 绑定 13 项 + 冻结 manifest 62 资产零漂移
  （chain_manifest 追加式演进经 git 历史实证）；独立重评分 30 题逐字段对账零差异；
  DB 直读核验（8 源、revs 逐 build 重算、独立 search→fetch 回环 3/3、d2d6 已 DROP）；
  纪律审计与静态门复跑全过；
- 探针产物：[m6-hashes.json](m6-hashes.json) / [m6-rescore.json](m6-rescore.json) /
  [m6-dbcheck.json](m6-dbcheck.json)。

## 不含范围（not_covered）

- prose 重抽取 2 例（not_run，待预算授权）；真实答案语义测试（not_run，待授权）；
  留出 10 格（held_out，守卫保护）；
- I4 迁移/清理/切换（M7）须按前置纪律另立授权与维护窗口；
- tasks.md 工作区改动未 commit，git 提交由 U 另行决定。

机器可读版：[signoff-record-m6.json](signoff-record-m6.json)（`signed_in: i0c-r5c`）。
