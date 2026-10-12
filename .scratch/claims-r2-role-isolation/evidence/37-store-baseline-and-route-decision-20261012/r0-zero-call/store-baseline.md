# store 层字段基线（路线 a/b 裁定依据）

- 预注册：`preregistered-store-baseline.json` `sha256:54195990ff317829c14dc8b75e489f0adaadb6c43b719f61a3876b165502ad00`
- 候选基线 = 生产 store 产物（**不是**门 33 工作台投影）

## store 运行对象

| 源 | extractor | items | slots | speakers | 未可归属 | 对象哈希 |
|---|---|---|---|---|---|---|
| industrial-fulian-md | `material-semantics-32` | 88 | 76 | 1 | 0 | `5164a8c10df8…` |
| optical-module-docx | `material-semantics-32` | 134 | 114 | 2 | 0 | `08fe8d9e4621…` |

## EC-A1 契约字段在 store 层的载体

| 契约字段 | 载体类别 |
|---|---|
| `proposition` | text_carried |
| `semantic_type` | item_field |
| `statement_role` | item_field |
| `speech_role` | item_field |
| `perspective` | item_field |
| `speaker_ref` | item_field |
| `polarity` | item_field |
| `attribution` | item_field_layer_b_coarse |
| `source_stance` | absent |
| `condition` | item_field_layer_b_coarse |

**零载体必需字段：['source_stance']**；载体存在但口径过粗：['attribution']

> layer B = `plugins/corpus/structured/store.py::_material_records`（store 自身的结构化投影），由 layer A + snapshot 确定性派生，实测调用真实函数得到；attribution 值域仅 document_voice/None，condition 值域为 conditional/unconditional，与金标口径不同。

### layer B（store 自身结构化投影，实测调用）

| 源 | 记录数 | attribution | condition | factuality | polarity | gold raw 一致 |
|---|---|---|---|---|---|---|
| industrial-fulian-md | 88 | {"document_voice": 88} | {"unconditional": 87, "conditional": 1} | {"fact": 49, "opinion": 18, "forecast": 21} | {"affirmed": 67, "negated": 17, "mixed": 4} | {"attribution": 0, "condition": 0, "semantic_type": 10} |
| optical-module-docx | 134 | {"document_voice": 132, "null": 2} | {"conditional": 5, "unconditional": 128, "null": 1} | {"fact": 49, "opinion": 30, "unknown": 24, "forecast": 31} | {"affirmed": 77, "null": 26, "negated": 30, "mixed": 1} | {"attribution": 0, "condition": 0, "semantic_type": 17} |

## EC-A2 逐字段一致性（覆盖槽位内，按金标记录）

| 字段 | raw 一致 | 归一化后一致 | 口径差可消 | 抽取差剩余 |
|---|---|---|---|---|
| `semantic_type` | 27/48 | 27/48 | +0 | 21 |
| `statement_role` | 21/48 | 21/48 | +0 | 27 |
| `speech_role` | 34/48 | 39/48 | +5 | 9 |
| `perspective` | 0/48 | 32/48 | +32 | 16 |
| `polarity` | 32/48 | 32/48 | +0 | 16 |

### 金标 vs store 分布

- `semantic_type`
  - gold：{"fact": 10, "opinion": 18, "forecast": 17, "behavior": 3}
  - store：{"fact": 98, "opinion": 48, "forecast": 52, "unknown": 24}
- `statement_role`
  - gold：{"evidence": 10, "claim": 18, "risk": 10, "condition": 10}
  - store：{"claim": 137, "evidence": 30, "condition": 6, "risk": 12, "other": 3, "question": 26, "answer": 8}
- `speech_role`
  - gold：{"statement": 48}
  - store：{"statement": 183, "unknown": 3, "question": 26, "answer": 10}
- `perspective`
  - gold：{"unknown": 41, "quoted_other": 7}
  - store：{"source_explicit": 220, "quoted_other": 2}
- `polarity`
  - gold：{"affirmed": 41, "negated": 6, "mixed": 1}
  - store：{"affirmed": 144, "negated": 47, "mixed": 5, "unknown": 26}

## EC-A3 归一化后元组对齐（覆盖槽位内）

| 元组 | 对齐记录数 | md（held-out） | docx（dev） |
|---|---|---|---|
| 5tuple | 7/48 | 3 | 4 |
| 4tuple_no_polarity | 10/48 | 5 | 5 |
| 3tuple_no_speech_role | 10/48 | 5 | 5 |
| 2tuple_core | 14/48 | 5 | 9 |

- 5 元组对齐记录：['NT-I01', 'NT-I02', 'NT-I05', 'NT-I22', 'NT-I26', 'NT-I28', 'NT-I44']

## EC-A4 说话人粒度

- gold 不同 attribution 数：5；gold 不同 speaker_ref 数：5
- store 不同 speaker_ref 数：{'industrial-fulian-md': 1, 'optical-module-docx': 2}
- store speakers 明细：{"industrial-fulian-md": [{"display_name": null, "identity_status": "unknown", "role": "document_voice", "speaker_id": "spk_544d7167e8a5"}], "optical-module-docx": [{"display_name": null, "identity_status": "unknown", "role": "document_voice", "speaker_id": "spk_544d7167e8a5"}, {"display_name": null, "identity_status": "unknown", "role": "quoted_source", "speaker_id": "spk_6c0e0ffe1a8f"}]}
- gold 内 attribution 与 speaker_ref 是否 1:1 冗余：True
- 可派生：**False** — store 侧只有 document_voice/quoted_source 两个说话人且 display_name 为空，gold 侧需 5 类区分（其中 attribution 与 speaker_ref 在 gold 内 1:1 冗余）⇒ 粒度不足，不可派生。

## EC-A5 门 33 投影缺陷

- workbench 相对 store 丢失的字段：['speaker_ref']
- 受影响 item 数：{"speaker_ref": 222}
- 影响 Stage 2 可执行性：**True**

## 路线裁定（按预注册 EC-A6）

**EC-A6a** — 路线 a 存在可执行路径（absent=['source_stance']，归一化后 5 元组对齐 7/48）；route b 不必为『字段缺失』而行。

- route a 代价：零模型调用：重建工作台（修投影，补 speaker_ref）+ 复用 store 自身已实现的 condition/attribution 派生（`structured/store.py:487-499`）+ 定枚举口径归一化条款 + 定 source_stance 条款；自动对齐记录数 = 7/48（见 ra_5tuple），其余靠人工裁定。零载体必需字段 = ['source_stance']；载体存在但口径过粗 = ['attribution']。
- route b 代价：改协议/口径后重抽：作废门 32 冻结 + 新门 + 真实调用（222 条候选重生）+ 重冻结；另需覆盖 9 条覆盖槽位内无候选的记录。其唯一不可替代之处是把口径写进协议而非事后映射。

## 与 r2 的冲突（待报告修订）

- EC-1（『4 个字段在候选上零载体』）须**收回重写**：零载体必需字段实测为 ['source_stance']；proposition 由 text 承载、speaker_ref 在 layer A 有载体、attribution 在 layer B 有载体（口径过粗）。
- §5.2/§3 L3 的候选字段数：layer A 语义字段 11（含 speaker_ref），门 33 投影 10，layer B 为 7。
- §5.8 的『route a 无法产出契约形态记录』：该结论只在门 33 投影口径下成立。
