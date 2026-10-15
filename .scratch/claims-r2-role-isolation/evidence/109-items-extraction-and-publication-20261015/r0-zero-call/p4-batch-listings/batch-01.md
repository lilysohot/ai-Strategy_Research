# 109 号 P4 批次清单 · 第 1 批（序号 1–20 / 共 10 批）

工作日：2026-10-15 ｜ 模型调用：0 ｜ 工件：`items-reextract-adjudication-r3-blank/candidate-adjudications.worksheet.json`（`47c56cea…`）

**性质声明**：下表"我建议"列为 assistant 的**校准提案**，不是裁定；裁定须 U 具名逐条落在工作表上。本批提案**不看预填件**（预填件已除名），只依据契约 v4.3 判据（含 `matching.items` 语义等价 + 「上下文唯一可恢复」及其两条不适用情形）、门 v3 与 75 号既有具名改判。

**判词表**：`matched`（命中金标）｜`correct_extra`（内容正确但不在 48 条金标内）｜`duplicate`（与已 matched 的另一条同义重复，只第一条可 matched）｜`incorrect`｜`out_of_scope`（无独立命题/声明范围外）｜`unresolved`

| 序号 | candidate_id | 命题 | 我建议 | 映射金标 |
|---|---|---|---|---|
| 1 | `itm_3131977b46dc2d03` | CSP/GPU 机柜量、Rubin 卡位、CPO/高速网络。 | out_of_scope △ | — |
| 2 | `itm_bf0c10772dfcb0bd` | 云计算 +75.7% | matched | NT-I05 |
| 3 | `itm_45f70982875f3a56` | CSP AI 服务器 +2.3 倍 | correct_extra | — |
| 4 | `itm_c21ff87ce469effd` | GPU/ASIC 机柜出货 +3.2 / +3 倍 | correct_extra | — |
| 5 | `itm_606114e59602a3a2` | Q2 营收 3067.83 亿环比 +22% | correct_extra | — |
| 6 | `itm_b88c5aa8e4cf9d93` | 但 OCF 只有 73.91 亿 | correct_extra | — |
| 7 | `itm_f10a2786bce96b74` | Q2 毛利率环比 −0.36pct | matched △ | NT-I07 |
| 8 | `itm_c462803f22154b00` | 并表 7% 的加工费没有变成「系统商」 | matched | NT-I08 |
| 9 | `itm_9beefa3f92899a14` | 扣非 229.84 亿同比 +97%，与归母 237.40 亿只差 7.56 亿非经常 | matched | NT-I01 |
| 10 | `itm_1b28a0df90711578` | 利润不是「公允价值把标题顶起来」 | matched △ | NT-I02 |
| 11 | `itm_7ba3125d387514f9` | 经营现金流 73.91 亿只盖住扣非的 0.32 倍 | matched △ | NT-I03 |
| 12 | `itm_326a165e24a204eb` | 存货 1921 亿、应收 1275 亿，高营收已经变成营运资本 | correct_extra | — |
| 13 | `itm_d34abd06836546b9` | 毛利率 7.15% 同比只加 0.55 个百分点 | correct_extra | — |
| 14 | `itm_3d0a3dc46e6837b4` | Q2 毛利率还从 Q1 的 7.35% 掉回 6.99% | correct_extra | — |
| 15 | `itm_9218124fbf3f3abe` | 现价 64.04 已从 6 月 84.95 回了约 25%，动 PE 26.76 在定价约 475 亿 26E | correct_extra | — |
| 16 | `itm_107df6dcd10427a6` | 估值没有把卖方 560–667 亿的 26E 盈利预测吃进去 | correct_extra | — |
| 17 | `itm_f4701ead02653e21` | 不按 93–101 的目标价去追 | correct_extra | — |
| 18 | `itm_fdda3d66d7e89956` | 不因为一天没涨就把 AI 机柜出货 +3 倍写成证伪 | correct_extra | — |
| 19 | `itm_6aacb1ab12e7e24d` | 少数股东 0.086 亿，几乎可忽略 | correct_extra | — |
| 20 | `itm_65a0b9716a7f3809` | 所以「净利润 237.49 亿」和「归母 237.40 亿」不必像生益那样拆并表子公司 | correct_extra | — |

小结：matched 6（NT-I01/I02/I03/I05/I07/I08）｜correct_extra 13｜out_of_scope 1 待定。

## 本批 4 个待你定的点

1. **序号 1**（`itm_3131977b46dc2d03`）：这是卖方提出的**议题枚举**，不是原子命题。按 66 号 `no_independent_proposition` 撤下口径应判 `out_of_scope`；但 `out_of_scope` 会从 precision 分母里移出，用宽了会虚高 precision，故我保守标"待定"。你定：`out_of_scope` 还是 `correct_extra`。
2. **序号 7 与 11 的 polarity 字段**：两条命题本身都是肯定式（"毛利率环比 −0.36pct"、"只盖住 0.32 倍"），但候选 `polarity=negated`，而金标 NT-I07/NT-I03 均为 `affirmed`。契约要求同义改写**保持语义类型与话语角色**（含 polarity）⇒ 若字段值算数，两条**不能**判 matched；若判定是抽取字段缺陷，则应先走字段修复再 matched。**请你定这条路**（我倾向：字段缺陷，先修字段后 matched，理由是与金标同义且证据逐字同源）。
3. **序号 7/8 与 10/11 共用同一句 quote**（`Q2 毛利率环比 −0.36pct，并表 7% 的加工费没有变成「系统商」。` / `不是「公允价值把标题顶起来」。但经营现金流 73.91 亿只盖住扣非的 0.32 倍，`）：这是本轮**原子化拆分**的正常形态（同一句拆成两条独立原子命题），**不是** `duplicate`；两条各自 matched 合规。请确认按此处理（后续批次同类情形我沿用同一口径）。
4. **序号 14**（`itm_3d0a3dc46e6837b4`）：注意它**不是** NT-I43 的载体——金标 I43 是**前瞻条件**（毛利率不再低于 6.99% 作为重开观察仓条件），本条是**现状事实**，故判 `correct_extra`。I43 在本轮池无独立载体（唯一载体是复合候选 `itm_8e932aaf49806db7`，已被 NT-I13 占用），属 `gold_split_finer_than_candidate` 机制，是本轮 md 源 18/22 上限的直接成因之一。

## 与已除名预填件的差异

本批与预填件结论**无差异**（预填同样给 I01/I02/I03/I05/I07/I08 六条 matched），差异只在：预填把序号 1 判 `correct_extra`（我建议 `out_of_scope`、待你定）、预填把序号 7/11 的 polarity 冲突直接忽略（我提出待定）。
