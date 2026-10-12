# P16 · 冻结链校验器（Wave 2，零调用）

- 来源：已签契约 v4.1 的 `bookkeeping_requirements.freeze_chain_validator_required`
  ——「任何契约/金标/manifest 修订须有校验器验证绑定一致（**现无**）」
- 实现：`tools/check_freeze_chain.py`（只读、零调用，有问题时以非零退出码作门）
- 首次运行：`freeze-chain-check.json`

## 一、它校验什么

| # | 绑定 | 判据 |
|---|---|---|
| 1 | 契约 v4.1 `threshold_source.authority_source.sha256` → 门 28 v1 文件 | 哈希相等 |
| 2 | 契约记录的阈值数值 vs 门 28 v1/v2 的 `quality_requirements` | 六项逐字相等 |
| 3 | 门 28 v1/v2 `gold.{freeze_manifest,freeze_state,frozen_gold}_sha256` → 实际文件 | 哈希相等 |
| 4 | 门 28 v1/v2 `gold.scoring_contract_sha256` 与 `metric_basis` | 等于已签契约则为 `ok`；落后则必须被**新版本记录覆盖**，否则计漂移 |
| 5 | `freeze-manifest.json.inputs`（8 条、裸 hex） | 逐条存在且哈希相等 |
| 6 | P12 记录声明绑定当前已签契约；且 `contract_snapshot` 已声明为历史 | 相等 + 存在声明 |

## 二、首次运行结果

```
ok = 13    covered_by_record = 3    drift = 0    needs_ruling = 1    exit_code = 1
```

**3 处 `covered_by_record`**（非失败——它们由新版本记录覆盖）：

| 项 | 说明 |
|---|---|
| `gate v1.gold.scoring_contract_sha256` 落后于契约 | 由 **P13** 新版本记录（`preregistered-gate-v2.json`）覆盖 |
| `gate v1.quality_requirements.metric_basis = …-v3` | 同上 |
| `freeze-manifest.json.inputs[…/scoring-contract.json]` 记 v2、实际 v3 | 由 **P12** 新版本记录（`rebinding-v4.1-20261012.json`）覆盖 |

## 三、1 项待具名裁定（`needs_ruling`）—— 由 P13 引出

**契约 v4.1 的权威门钉在 v1 上，而 P13 已产生继任记录 v2 ⇒「哪一份门是权威」需要你定。**

- `contract v4.1.threshold_source.authority_source.sha256` = `sha256:987772e9…`（门 28 **v1**）
- P13 后新出现 `preregistered-gate-v2.json` = `sha256:8cc11bcc…`
- **阈值数值经实测逐字相同**（六项），故**不影响口径**；影响的只是"权威"的指认。

两个选项：

- **(a)** 契约出新版本，把 `authority_source.sha256` 改钉 v2 ⇒ 契约要再签一次。
- **(b)** 明确分工：**v1 = 冻结执行门**（绑 v3，是当时真实执行的依据，字节不得动），**v2 = 基准持有记录**（绑 v4.1）；契约的钉法保持指向 v1 并加一句说明。

我倾向 **(b)**：v1 是"当时真的这么跑"的证据，改它或改契约去钉 v2 都不增加信息量，而 (b) 用一句说明就消除了歧义。

> 在此之前，本校验器**保持非零退出**（有未裁定项即不放行）。这符合它的定位：它不替你做决定，只把"绑定不一致"变成可见的失败。

## 四、边界（不宣称）

- 校验器只核**绑定一致性**：不评价金标语义、不产生门分数、不做任何修正。
- 它对"落后但被新版本记录覆盖"的绑定判 `covered_by_record` 而非 `ok`——两者含义不同，不得互相代替。
- 已知不覆盖：`structured_scoring.py` 的硬编码阈值（0.95/0.90）与契约口径的冲突**不**在本校验器的检查范围内，属 **P03**。
