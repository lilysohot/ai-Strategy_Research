# 契约 v4.2 · 审阅件（待签）

- 本件：`/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/57-contract-v42-draft-20261012/r0-zero-call/contract-v4.2-review.md`
- 状态：**draft_pending_human_signature**（签认前不生效；v4.1 字节不变）

## 一、这份签下去等于什么（一句话）

把契约里「权威阈值源」的指认从门 28 的**冻结执行门（v1）**改钉到 **P13 产出的基准持有记录（v2）**。这是你对 P16 校验器拦下那项的裁定 **(a)** 的落实。

**阈值数值逐字不变**；除下表 3 处（外加版本号/supersedes/签认态/修订史）外，其余叶子零改动（机器 diff 证明）。

## 二、改动清单（机器 diff，共 9 处 changed）

| 叶子 | v4.1 | v4.2 |
|---|---|---|
| `schema_version` | 见 diff 件 | 见 diff 件 |
| `status` | 见 diff 件 | 见 diff 件 |
| `supersedes.note` | 见 diff 件 | 见 diff 件 |
| `supersedes.schema_version` | 见 diff 件 | 见 diff 件 |
| `supersedes.sha256` | 见 diff 件 | 见 diff 件 |
| `threshold_source.authority_source.sha256` | 见 diff 件 | 见 diff 件 |
| `threshold_source.authority_source.where` | 见 diff 件 | 见 diff 件 |
| `threshold_source.effective.source` | 见 diff 件 | 见 diff 件 |

- `schema_version`：`…-v4.1` → `non-table-selected-target-scoring-contract-v4.2`
- `threshold_source.authority_source.sha256`：`987772e9…`（门 v1）→ `8cc11bcc…`（门 v2）
- `threshold_source.authority_source.where` 与 `threshold_source.effective.source`：改指 v2 文件
- `supersedes` / `revision_history` / `status` / `signoff`：随版本推进

- `unexpected_changed`：**0**（必须为 0）
- `threshold_values_unchanged`：**True**

## 三、不改什么

- 六项阈值数值：`0.85 / 0.80 / 0.80 / 40 / 20 / 0`（机器校验通过）
- 已签 v4.1 的字节（`c76ac13e…`）
- 门 28 v1（冻结执行门，`987772e9…`）与门 28 v2（`8cc11bcc…`）的字节
- 冻结金标、freeze-manifest、freeze-state

## 四、裁定依据

- U 2026-10-12 裁定 **(a)**：契约出新版本改钉 v2（回应 P16 校验器的 `needs_ruling`）。
- 手续：沿用 P12/P13 的『新版本记录 + 旧哈希留存』；本次是契约自身的版本推进，故需再签一次。

## 五、签认栏

- 复核人：　　　xyl　　　日期：2026-10-12
- 结论：☑ 认可并签认 v4.2　　☐ 退回修改
- 备注：

> 签认后：v4.2 落 `47-…` 同级的**新签认目录**；契约绑定链变为 v2 → v3 → v4 → v4.1 → v4.2；P03（评分器读契约）以 v4.2 为准。
