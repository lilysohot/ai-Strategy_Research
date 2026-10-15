# 109 号 P4：工作表重出 + 预填除名记录（2026-10-15，零模型调用）

机器件：`p4-worksheet-reissue-and-prefill-void-record.json`
`sha256:b5ca0ae0ff2906915bd4e43291a5a00009d180b5089b00f3ee3d8a10732d2d74`

## 一、你的裁定

**乙 + 工作表重出**（2026-10-15）。

- **乙**＝门判档按 round-3 **单池**如实读数；跨轮累积读数为登记对照，**不是判定池**；发布按 72 号既定**解耦**路线（发布标准与门阈值/金标解耦）另行放行。
- **甲（并池作判定池）否决**：`round3-landing-record.json` 自述「禁止看过结果后挑池」；77 号的并池是当轮邻批、且在重算前已具名，形态不同。

## 二、发现的事故

`MANIFEST` 登记的空白工作表（`47c56cea…`）在盘上被**全量预填**成 `a5869ab1…`，并带了签署面：

| 项 | 实然 | 应为 |
|---|---|---|
| 199/199 行 `reviewer` | `"U"` | 留空 |
| `adjudicator` | `"assistant"` | 留空 |
| `review_status` | `"accepted"` | `pending_named_human_signoff` |
| `judgement` / `matched_gold_id` / `reason` | 已填 | 留空 |

违反：预注册 v2 `adjudication_clause`「U 具名（xyl）全量逐条」；立项验收判据 3「机械预填不得替代或污染人工校准记录」。

**可复现性证明**：把预填件的上述 6 个字段按构建器初值还原后逐字节 `hash = 47c56cea…`（＝ MANIFEST 记录值）⇒ 预填只动了这 6 个字段，**没有**动候选、判据与冻结指针。

**处置**：按 67 号先例**除名**——不作裁定依据、不进入装配与评分；原文件**字节未改、未删除**，作为事故证据留档。

## 三、重出结果

| 件 | 目录 | sha256 |
|---|---|---|
| 工作表（空白签认版） | `items-reextract-adjudication-r3-blank/` | `47c56cea…` |
| stage2 闸 | 同上 | `2bb5ccb9…` |

两件哈希与 MANIFEST 记录值**逐字相同** ⇒ 重出的是与 MANIFEST 一致的**原定仪器**，不是新变体（仅目录名不同，因原目录已被预填件占用）。199 候选 + 29 条 C1 checklist，全部字段留空。

## 四、预填件的复核结论（为什么必须重出，而非"认账即可"）

零调用、真代码路径复算：

| 情景 | 召回 | 分源 | 判定 |
|---|---|---|---|
| A 现状 | — | — | **不可出分**：`gold NT-I14 matched twice`（违反 one_to_one_mapping） |
| B 仅修 8 条重复映射 | 41/48 = 0.8542 | md 18/22、docx 23/26 | FAIL（md accepted 18<20；哨兵缺 NT-I43） |
| **C ＋撤回 I46/I47**（回到 U 2026-10-12 校准） | **39/48 = 0.8125** | md 18/22、docx 21/26 | **FAIL（4 项卡点）** |

C 即本件登记的 **round-3 单池预期读数**。另登记诊断对照：跨轮累积 42/48（`I06←r5`、`I43←base`、`I26←75 号改判`），**不并入判定池**。

## 五、下一步

1. **P4**：你在 `items-reextract-adjudication-r3-blank/` 上具名全量逐条裁定；assistant 每 20 条列一批清单留档。
2. **P5**：单池出分 → 你具名签认放行。
3. **P6**：发布（`--import-items-artifact` → `plan_batch(imported_material_items)` → `publish_semantic` 全门 → 生产 store coverage `missing→complete`）；放行理由写"结构完备 + coverage 补全 + 缺口清单明示"，**不写"门 PASS"**。
4. **P7**：零调用 web items 查询端点 + 常驻测试 + 落地记录。

## 六、边界

未写生产 PG、未发布任何东西；未改任何已签/已冻结字节（83–108 号、pre-reg v2、freeze、MANIFEST 均未动）；未代签、未预填任何签认栏。
