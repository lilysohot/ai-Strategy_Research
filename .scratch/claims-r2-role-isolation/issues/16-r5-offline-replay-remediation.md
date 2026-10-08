# 16 · r5 零模型重放与局部依赖修复

Status: implementation and offline replay complete; ready for a separately bounded r5 live continuation

Execution: 未调用真实模型；复用 r4 工业富联的 17 份已保存 `material_items` 响应，在 r5 校验器下完成离线重放。最终结果为 92 items、78/78 extracted、items 协议 valid、质量 accepted；从 92 个合格端点确定性生成 4 个 relations 候选。

Blocked by: 相同 24 单元尚未形成完整 Claims/items/relations 候选名册。工业富联 Claims 的一个历史 `outcome_unknown` 没有可验证的 provider 结果，光模块来源尚未执行，relations 仅生成候选而未调用模型；因此不得发布、不得进入 query/delivery/context_use，也不得开始完整三角色人工裁定。

## 本轮目标

本轮只修复 r4 已证明的协议和执行问题，不重新制作金标、不改变 24 单元分母、不调用模型寻找“幸运结果”：

1. 未知或截断槽位 ID 仅在逐字引文唯一落入一个槽位时回绑；歧义或槽位外引文继续 fail-closed。
2. 显式命题否定由系统确定性归一；风险中的“不是 A，而是 B”保留整体风险为 affirmed，但其逐字引文足以覆盖 negation 信号。
3. relations 从 `coverage.slot_ledger.status=extracted` 的 item_refs 派生端点；partial/failed 槽位不再阻断无关合格端点。
4. 公共执行账暴露 `endpoint_item_ids`，便于核查关系任务实际使用的端点集合。
5. 真实 HTTP 请求增加稳定 `Idempotency-Key=attempt_id`；`outcome_unknown` 仍禁止自动重发。

## 版本

- material extractor: `material-semantics-22`
- item protocol: `material-atomic-jsonl-v5`
- item validation: `material-items-validation-v5`
- relation candidate rule: `material-relation-candidates-v3`
- HTTP adapter: `structured-chat-http-2`

协议字段没有再次变化，`material-atomic-jsonl-v5` 保持不变；本轮变化属于校验、端点派生和传输身份，因此分别提升 validation、candidate rule、extractor 与 adapter 版本。

## 回归结果

- 聚焦回归：135 passed。
- corpus 全套：1318 passed、17 skipped、2 个既有环境/基线失败：
  - golden retrieval 当前样本库为 0/20；
  - PDF smoke test 仍期待 `reader-pdf-10+`，实际为 `reader-pdf-11+`。
- Ruff：通过。
- Pyright：0 errors、0 warnings。

新增回归覆盖：

- 错误槽位 ID + 唯一逐字引文可以回绑；
- 槽位外引文不得回绑；
- 三个 r4 显式否定样例由系统归一；
- affirmed 风险对比句覆盖 negation 信号；
- items 整体 review_required 时，relations 只使用 extracted 端点子集；
- execution ledger 对外显示关系端点；
- HTTP 请求携带与账本 attempt 一致的幂等键，并保持未知结果不重发。

## 真实响应离线重放

基线 r4：

- 17/17 items HTTP 响应已保存；
- 91 个可见 items；
- 74 extracted、3 partial、1 failed；
- relations 因整工件门禁未派生。

r5 最终离线重放：

- 17/17 原响应逐一按对象哈希绑定；
- 92 items；
- 78/78 extracted，10/10 packet completed；
- items execution/protocol/quality = succeeded/valid/accepted；
- 92 个合格 relation 端点，4 个确定性候选关系；
- 新模型调用 0，relation 模型调用 0；
- snapshot 仍为 `sha256:d6546966ac517902659ed66c4fbdc7efd8512725a0ba1ef9d507844718bac055`。

最终证据：

- `../evidence/16-r5-zero-model-replay-20261008-r4/manifest.json`
- `../evidence/16-r5-zero-model-replay-20261008-r4/industrial-fulian-md/summary.json`
- `../evidence/16-r5-zero-model-replay-20261008-r4/industrial-fulian-md/relation-candidates.json`

`16-r5-zero-model-replay-20261008/`、`-r2/` 和 `-r3/` 是同轮的追加式中间证据：前者暴露最后一个风险对比句问题，后两者验证修复但早于最终只读源数据库保护；不得把它们冒充最终冻结结果。

## 后续执行约束

下一次真实执行必须建立新 batch，不修改 r3/r4 历史账：

1. 复用现有签认金标，不重新标注。
2. 工业富联 items 可以直接使用本轮哈希绑定的 accepted 离线重放工件，不为验证校验器而再次调用模型。
3. Claims 的历史 unknown 只能通过 provider 可验证回查或新建、明确记录的最小范围任务处理；不得把 unknown 自动重发伪装成 retry。
4. 光模块 Claims/items 按冻结预算执行；只对合格端点派生 relations。
5. 完成相同 24 单元的三角色候选名册后，才做一次逐条人工裁定，并继续 publication、query、delivery、context_use 观察。
