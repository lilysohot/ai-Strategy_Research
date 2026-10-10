# Issue 26 · relation 层价值最终裁决

Status: closed

## 结论

**不保留默认 relation 富化；R2 默认交付回到 items-only，验收重心回到 material_items 的证据完整性。**

## 解盲结果

- Q1：baseline 更好；treatment 出现不可追溯表述。
- Q2：相同。
- Q3：相同。
- Q4：baseline 更好；treatment 留下错误 challenges 的“挑战/刷新”语义痕迹。
- Q5 控制题：相同。

treatment 在 Q1—Q4 中提升 0 题、回退 2 题、持平 2 题，未达到“至少提升 3/4 且其余不下降”的保留门。

## 成本

- B 相对 A 的中位输入 token：+24.33%。
- B 相对 A 的中位总 token：+40.74%。

质量没有提升且输入 token 增幅超过 20%，成本止损同时触发。

## 执行政策

- 默认：只交付 material_items。
- relations：保持非阻断、按需实验，不作为当前 R2 验收或发布前置条件。
- Issue 27 的 challenges 高精度收紧继续保留，但不因此复活已关闭的默认 relation 路线。
- 不修改 gold-v2；本裁决只回答下游业务增益。
