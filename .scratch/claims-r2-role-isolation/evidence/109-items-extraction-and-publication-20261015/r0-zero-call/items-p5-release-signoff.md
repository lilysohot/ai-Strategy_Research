# items 门评分与发布放行（109 号 P5）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。
**签署后请把上一行改成「已签认」。** 本件正文状态行与签名栏冲突时以**签名栏为准**（109 号两份既有签认件曾因状态行未随签名更新而产生摩擦，故在此写明）。

零模型调用、零生产 PG 写入。本件只做一件可执行的事：授权起跑 P6（发布）与 P7（读链）。

## 一、本件签认的对象（放行范围逐字绑定）

签认范围绑定到**一个具体修订**，不是"这一类件"：

| 项 | 值 |
|---|---|
| 放行件 | `evidence/109-items-extraction-and-publication-20261015/r0-zero-call/p5-release-record.json` |
| 其 sha256 | `a035b06843a67c26f0c11081471231975140f5b742e4f1a7d78de66ae0478e7b` |
| 判定模式 | `structured_scoring.MatchingMode.ADJUDICATED`（只消费人工裁定映射，零金标注入） |
| 判档 | **FAIL（单轴）**：判定轴 5 项中 4 项达标、1 项（哨兵 **NT-I43**）未达标 |
| 合同层布尔 | `rate_gate_passed = false`（逐字保留，不参与判档措辞） |
| 召回 / 精度 | 41/48 = 0.8542（≥0.85）；191/199 = 0.9598（≥0.80） |

若该件哈希在签认后被改动，本签名不再指向新修订——须另立取代登记。

## 二、判档口径的依据（已获 U 认可）

三层读数并列登记（合同布尔 / 条数下限派生复算 / 判定轴），三读在「唯一实质未达标 = 哨兵 NT-I43」上收敛：

- 判定轴路径：预注册 v2 `reading_axes` 五轴，唯一未达标为哨兵；
- 合同自身派生复算：`floor(0.85×48)=40` 与合同 total 下限逐字相符 ⇒ 规则即合同自有；合同的 `per_source=20 = floor(0.85×48/2)` 来自「两源均分」假设，按实际目标 22/26 复算为 18/22，md 实测 18 恰在线上；
- 认可件：`p5-c1-reading-ratification.json`（`cd7d5479…`，`stated_effective_pending_countersignature`）。

未改合同 v4.3、评分器、阈值、预注册任何字节。

## 三、签认的效力

签认后允许执行（两步均零调用、不写生产 PG）：

- **P6 发布**：`structured/cli.py --import-items-artifact` → `plan_batch(imported_material_items=…)` → `publish_semantic` 全门 → 生产 store 两源 `material_items coverage: missing → complete` → 查询验收；
- **P7 读链**：web items 查询端点 + 常驻测试 + 落地记录 + MANIFEST。

发布依据（72 号既定解耦路线）：**发布标准（结构完备性）与门阈值/金标解耦**，`store.py` 对 gold/recall/assertion 零引用；发布理由写「结构完备 + coverage 补全 + **缺口清单明示**」，**不写「门 PASS」**。

## 四、发布件必须逐条列出的显式缺口

不得只写总数。清单来源：`p5-release-record.json::explicit_gaps`。

1. **金标侧未覆盖 7 条**：`NT-I06 / NT-I09 / NT-I10 / NT-I25 / NT-I26 / NT-I31 / NT-I43`
   （其中 **NT-I43 为哨兵且 critical**；round-3 全量重抽 24 attempts 后仍缺，池内最高字面相似度 0.121–0.333 ⇒ 非额度问题）
2. **claims 欠账侧 12 条**（`covered 17 / no_candidate 12`，来源 `p4-c1-disposition-final.json` `e6cc2347…`，你已逐条裁定）：
   `#2 / #7 / #9 / #12 / #13 / #14 / #17 / #19 / #20 / #24 / #27 / #28`
   其中 U 显式点名 5 条（#2/#9/#17/#20/#24），未点名按机械初判落档 7 条（#7/#12/#13/#14/#19/#27/#28，可随时更正）。

## 五、不含在本件签认内的

- **C-2**：已闭合（你明确不授权机械裁定，并已逐条给出方向）——无需本件再裁；
- **C-1 读法认可件**：已按会话口谕生效（`stated_effective_pending_countersignature`），如需具名可另补签，不阻塞本件；
- **两份既有签认件正文状态行与签名栏不一致**（`items-extraction-publication-signoff.md`、`items-reextraction-preregistration-signoff.md`）：已按「以签名栏为准」登记，字节未改；若要修正正文须另立修订版 + 取代登记（选项 C），不在本件内；
- **material_relations 角色**：本轮不抽不评（契约 OPEN-2=C），范围显式披露；
- **生产 PG 任何写入**：不在范围内。

## 六、assistant 已定项（签认时可否决）

1. P5 判档按 `reading_axes` 读为「单轴未达标」，合同层布尔并列保留；
2. 29 条处置以 `p4-c1-disposition-final.json` 为唯一权威来源，工作表 `-c1ruled` 修订版为落位件；
3. P6 走既有桥与全部门，不动 83–108 号已落地产物字节；
4. P7 items 读链端点纳入范围。

## 签名

reviewer:   xyl       adjudicator:   xyl       signed_on: 2026-10-15
