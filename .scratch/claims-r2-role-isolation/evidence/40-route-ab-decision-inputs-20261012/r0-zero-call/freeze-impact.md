# route b 冻结影响清单

- 触发条件：任一改动 material_semantics.py 提示词文本 / 协议版本 / 装配投影

## 受影响（逐条）

| 物件 | 绑定来源 | 影响方式 | 处置 |
|---|---|---|---|
| gate-32 freeze-manifest 输入 material_semantics_module | gate-32 freeze-manifest inputs | 直接失配（该文件是绑定输入） | 新冻结（新版本记录，旧哈希留存），须新门 |
| gate-32 freeze-manifest 输入 structured_config_module | gate-32 freeze-manifest inputs | 若同时改配置则失配；仅改提示词则不受影响 | 按实际改动面决定 |
| gate-32 freeze-manifest 输入 structured_adapter_module | gate-32 freeze-manifest inputs | 若改装配投影则失配（工作台投影缺陷即在此层） | 按实际改动面决定 |
| gate-32 四个 plan 文件 | gate-32 freeze-manifest files_sha256 | 协议/快照变更会改 plan 内容 ⇒ 4 个哈希全部失配 | 重新 plan（零调用）并新冻结 |
| 金标冻结链 freeze-manifest 输入 scoring-contract.json | 金标冻结链（Issue 10） | **已漂移**：记录 v2，实际签认 v3（7/8 匹配）；契约 v4 会再漂一次 | 与 C1/C3 同轮修绑定（新版本记录，不改金标字节） |
| 门 28 preregistered-gate（signed，权威阈值与字段清单来源） | 门 28 自身 | v4 若改 metric_basis / role_required_fields ⇒ 门 28 度量基准失配 | 新版本门记录（不就地改） |
| 门 33 workbench v1 | 门 33 自身 | route b 改协议 ⇒ 候选集变化 ⇒ v1 与 v2 均作废 | route b 须重建工作台（零调用，复用 evidence/38 脚本） |
| 门 33 adjudications 骨架 | 门 33 自身 | 候选集变化即作废（现为空骨架，未填） | 随工作台重建 |
| treatment store 对象（现 extractor material-semantics-32） | 运行产物本身 | 推进 extractor_version 后旧产物须保持可读，否则 222 条候选读不回 | 登记 _HISTORICAL_RUN_PAYLOAD_SHAPES（对应 B3） |

## 声明不受影响

| 物件 | 理由 |
|---|---|
| frozen-gold.json / freeze-state.json | 金标字节不动（§8 范围外硬约束）；只修其 manifest 里的契约绑定记录 |
| plugins/corpus/structured_scoring.py | 不在 gate-32 freeze-manifest 的绑定输入清单内（已核对；仍建议在 v4 轮显式确认一次） |

## 摘要

- `direct_hash_mismatch`：['material_semantics_module', '四个 plan（协议变更时）']
- `requires_new_gate`：True
- `requires_new_freeze`：True
- `gold_bytes_untouched`：True
- `historical_readability_risk`：旧 222 条候选须保持可读（B3）

> 6fb47e79…fba8（issue-34 §2 记载；本批未重算，需在执行前复核）
