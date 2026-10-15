# items 抽取与发布 立项（109 号）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。
立项本身零模型调用；**不写生产库任何表**；不改 83–108 号任何已落地产物。
U 于 2026-10-15 指示立项（『由你定』）；门分判档与发布放行仍须 U 具名签认。

## 一、题目

把 material_items 角色从「历史冻结池 PASS（门 33，41/48）」推进到与 claims 链
（95–108 号）同构的终态：**当前代码重抽 → 人工裁定 → 门评分 → 生产发布 → web 读链**。
这是 claims 链完结后 items/relations 两角色中唯一可评分的一个
（relations 属 OPEN-2=C，本轮不纳入、范围显式披露）。

## 二、现状（零调用探查，见 current-state-scan.json）

- items 无 claims-treatment 式三件套（102/105 号脚本均 hard-wire claims 判据）；
  原始 222 条池来自门 32 冻结链（`evidence/28-…/freeze_items_only_plan.py`，
  协议 `material-atomic-selector-jsonl-v1`，expected_attempts md10+docx14）。
- 裁定与评分侧 items 原生已在位：38 号工作台工具链、`adjudication_assembly.py`
  （永不读金标）、`structured_scoring.py` ADJUDICATED 模式、items 门 v3 判据。
- 判据轴 = 现行 `SIGNED_SCORING_CONTRACT_PATH`（v4.3，75 号）；v4.4 的
  `role_sections.material_items` 是 v4.3 镜像（11 条 NT-I + target 48），逐字等价，
  **不切换**（切换属纯簿记、无判据增益）。
- 发布桥已在位（`plugins/corpus/structured/cli.py` `--import-items-artifact/payload`
  + `AcceptedMaterialItems` + `plan_batch(imported_material_items=…)`），
  但生产 store 两源 coverage 均 `material_items: missing`（items 尚未发布）。
- 92 号 29 条角色外 claims 候选全部 `owner_role=material_items`、`pending_coverage`，
  登记件自述「须由对应角色的门另行出分」⇒ 是本项目的登记输入，不得就地丢弃。
- 108 号生产 store 落位 + 四只读端点已在位，但 signoff 件**未签认**；
  items 查询端点不在 108 范围，由本项目 P7 补齐（零调用）。

## 三、计划（P0–P7；唯一花钱轮 = P2）

| 步 | 内容 | 模型调用 |
|---|---|---|
| P0 | 立项（本件）签认 + 预算授权 | 无 |
| P1 | 零调用：items 版预注册 + 冻结计划 + 工程缺件三件（参照 102 号 claims 形态：prepare 冻结两源计划 / execute 六道 fail-closed 闸门 / worksheet 构建器逐字读已签判据）；判据写死 = 门 v3 六项（0.85/0.80/0.80/0）+ 哨兵 11 + target 48；止损规则与 Stage-1 证据链权重预注册固定；92 号 29 条登记为工作台输入 | 无 |
| P2 | 活跑重抽：当前代码版本全量重抽两源 material_items（协议 `material-atomic-selector-jsonl-v1`），按授权件 ceiling 对账、超限判该轮无效；P1 签认前禁止起跑 | **唯一花钱轮** |
| P3 | 零调用：阶段止损复核（从已签预注册件逐字读规则）+ Stage-1 建议器（带可核验证据链，禁金标注入） | 无 |
| P4 | Stage-2 人工裁定：U 具名全量逐条；assistant 每裁完一批（20 条）即列出该批候选清单（序号/candidate_id/命题/裁定/映射金标）留档；含 92 号 29 条处置（有对应候选入裁定、无候选记 no_candidate） | 无 |
| P5 | 门评分：ADJUDICATED 喂 structured_scoring（零金标注入、只消费人工裁定映射），items 门 v3 判据出分判档；U 具名签认放行 | 无 |
| P6 | 发布：accepted items → structured CLI 桥 → `plan_batch(imported_material_items)` → publish_semantic 全部门 → 生产 store（coverage missing → complete）+ 查询验收 | 无 |
| P7 | 零调用：web 读链 items 查询端点（补 108 号的 items 对应物）+ 常驻测试 + 落地记录 + MANIFEST | 无 |

## 四、验收判据（执行前写死）

1. 判据写死先于花预算与人工裁定；线值/哨兵/target 与门 v3 逐字一致，
   不因看到新池结果而改；
2. 唯一花钱轮 = P2；按授权件 ceiling 对账，超限判该轮无效（与 103 号同语义）；
3. Stage-2 全量逐条 U 具名裁定；批次清单按批留档；机械预填不得替代或污染人工校准记录；
4. 评分只消费人工裁定映射（ADJUDICATED），候选生成零金标注入；判档读数只按预注册轴；
5. 发布走既有桥 + publish_semantic 全部门；生产 store material_items coverage 补全，
   既有 claims 发布件字节不动；
6. 零调用步骤零模型调用；生产 PG 零写入；
7. 83–108 号已落地产物字节未动（108 号 signoff 保持 draft 态，其签认与本项目解耦）；
8. 常驻测试 + ruff/pyright + import_smoke/check_symbols 干净。

## 五、assistant 已定项（U 签认时可否决）

1. 判据轴沿用 v4.3 现行指针，不切 v4.4（items 轴逐字等价）；
2. 92 号 29 条纳入 P4 工作台处置，不另开链；
3. 工程缺件按 102 号 claims 形态新写 items 版三件（判据从已签件逐字读，不硬编码）；
4. P7 items 查询端点纳入范围（零调用）。

## 六、待裁项（集中一次问）

| # | 类别 | 内容 | 状态 |
|---|---|---|---|
| 1 | ①类（花模型额度） | P2 预算 ceiling（total_tokens）与 attempts 上限。参照：claims 治理轮实测 246,303 tokens / 19 attempts（约 12,963/次）；items 门 32 冻结 24 attempts；2026-10-13 双臂补跑授权 30+30；assistant 建议 ceiling = 1,000,000 tokens（同 claims 103 号口径，约 3–10 倍余量） | **留空待 U 填定/调整** |
| 2 | 立项签认 | 本件签认后 P1 开工；P2 起跑另须预算格非空 | 留空 |

## 七、放行判定

P5 门分与 P6/P7 落地只形成**落地记录**；「items 可发布/可消费」的放行由 U 具名签认
（独立复核 + U 签认，实施方不自宣）。

## 签名

reviewer:     xyl     adjudicator:     xyl     signed_on:2026-10-15

预算 ceiling（total_tokens）：  1000000        attempts 上限：30
