# 契约 v4.2 · 已签认版

- 签署人：**xyl**　日期：**2026-10-12**
- 签署工具：`.scratch/claims-r2-role-isolation/evidence/57-contract-v42-draft-20261012/r0-zero-call/contract-v4.2-review.md` `sha256:215a3490e9e9c6fc70b482347438b36f7f9c9166d6869c44a4b2f2063f1b2f20`
- 产物：`scoring-contract-v4.2.json`（`status = frozen_signed`）
- 取代：已签 v4.1 `sha256:c76ac13ec0a109074775a2b5e1c8cc170da955847638d6ea7f5778988238781b`（字节不变，留存可追溯）

## 本轮唯一实质改动

- `threshold_source.authority_source` 由门 28 **冻结执行门（v1，`987772e9…`）**改钉**基准持有记录（v2，`8cc11bcc…`）**——落实 U 的裁定 (a)。
- 机器 diff：`changed 9 / unexpected 0 / 阈值六项逐字不变`。

## 签认之后仍未完成（不得读成已过门）

- P03 阈值单源落地：评分器改为读契约（OPEN-1=A 的兑现）——现在以 v4.2 为准
- P04/P05 口径归一化实现与回归
- gate v2 的 metric_basis（…-v4.1）现落后于契约 v4.2：是否推进属『契约↔门 相互追逐』问题，建议以『阈值数值恒等』为不变量、由校验器持续核查（见 56-…/README.md §三 的选项 b 精神）
- route a/b 边际裁定与缺口 1/2

> 签认只签契约条款；不等于 items-only 真实复验通过，也不等于门 33 出分。
