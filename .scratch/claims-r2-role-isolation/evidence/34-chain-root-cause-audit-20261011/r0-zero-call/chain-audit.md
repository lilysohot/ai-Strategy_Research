# items 数据链路根因核查（issue 34）

- 输入哈希：见 `chain-audit.json.inputs`

## L1/L2 源 → 快照 → 槽位粒度
- 每条金标覆盖的候选槽位数分布：{1: 42, 2: 6}
  （42/48 条金标落在单个槽位内、6 条跨 2 槽、0 条落空 → **粒度基本对齐，不是根因**）

## L3 字段契约对比
- 契约必需字段：['proposition', 'semantic_type', 'statement_role', 'speech_role', 'perspective', 'speaker_ref', 'polarity', 'attribution', 'source_stance']
- 候选语义字段：['text', 'semantic_type', 'statement_role', 'speech_role', 'perspective', 'polarity', 'value', 'behavior_status', 'temporal_frame', 'unknown_fields', 'speaker_ref']
- **契约有、候选没有**：['attribution', 'proposition', 'source_stance']
- 候选有、契约没要求：['behavior_status', 'temporal_frame', 'text', 'unknown_fields', 'value']

## L4/L5 协议与校验
- v6 提示词：treatment 0 次协议违规（control 11 次）；fail-closed 未放宽

## L6 装配
- 候选 222 条；未产出槽位 {'infrastructure': 7, 'model_behavior': 0, 'our_contract_signal_overlabelling': 2, 'unclassified': 0}

## L7 评分契约 vs 评分器实现
- 契约 v3 要求：condition 载体、compound_condition 子条件计分、proposition/attribution/source_stance
- 评分器实现：只有 `identity` 精确相等匹配（无上述任一读路径）

## L8 金标构成
- 48 条：critical 12、risk_or_condition 21、condition 角色 10

## L9 可执行实测：语义相同、字段不同会怎样
- 用金标字段形态的候选：{'tp': 19, 'fp': 0, 'fn': 29, 'matched_gold': 19, 'recall': '19/48', 'precision': '1/1'}
- 用候选原生字段形态：{'tp': 0, 'fp': 19, 'fn': 48, 'matched_gold': 0, 'recall': '0/1', 'precision': '0/1'}

## 根因结论
- Not every layer is broken. Sources, snapshots, slot splitting, the v6 prompt, the fail-closed validator and the assembly all check out (42/48 gold records even sit inside a single candidate slot). The break is at exactly one seam: the extraction schema and the scoring contract describe different records. Candidates carry text/semantic_type/statement_role/speech_role/perspective/polarity/speaker_ref; the contract requires proposition/attribution/source_stance and, for condition-role records, a condition carrier. Contract v3 was signed on 2026-10-11, after the selector protocol had frozen, and it added read-path rules (condition carrier, compound_condition sub-condition scoring) that the scorer never implemented — it still matches on exact field equality. Because the required fields are absent, the human step cannot be a field mapping either: it becomes rewriting propositions from raw text, which is what the contract explicitly forbids doing by hand-off.

### 修复顺序
- 1) settle the field-carrier question: either sign a read-path rule that lets candidate text be canonicalised into the contract's proposition/condition carriers (cheap, but must state how equivalence is evidenced), or extend the items protocol with those fields and re-extract (costlier, produces contract-shaped data)
- 2) implement the v3 read path in the scorer (condition carrier + compound_condition sub-conditions), otherwise condition-role gold can never match
- 3) fix the Stage-1 helper (or accept that adjudication is manual) before reading anything into the 19/48 number
- 4) only then adjudicate and score; precision stays N/A until unresolved is zero
- 5) re-run the single lost packet under a new gate if the seven critical gold records matter for the decision
