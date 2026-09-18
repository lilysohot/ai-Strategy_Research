# I3-2 复验 B1—B5 修复交付（2026-09-18）

## 状态与范围

本轮已实现五类审批/投影修复并通过定向回归，候选规则更新为 `evidence-mapping-6`；冻结修订为 **i0c-r25**（仅冻结候选工具链与本轮证据，不是正式金标批准）。最终冻结校验命令输出见 `freeze-validation.txt`。

**真实批准仍为 `no_decisions / ready=false`，I3-2 与 M6 不宣告完成。** 没有代填 U 审批、没有新增模型预算、没有读留出/原文 PDF/候选业务结果，也没有连接或写入 PG。source/query gold、评分器、清洗/切块/数据库与公共模块未修改。

诊断使用 diagnosing-bugs 技能：先把上轮反例固化为会失败的断言，记录红灯，再修复并复跑原始场景。本轮不重复已完成的泛化归因。

## 修复映射

| 报告项 | 实现 | 验证 |
|---|---|---|
| B1 来源专属绑定 | 指定来源的 chosen 必须属于该 source_id；投影终检再次核对来源义务 | 错来源失败、正确双来源成功；company-008 全量旧绕过被阻断 |
| B2 答案约束与证据隔离 | answer_constraint 不接受 chosen/锚点映射；不投影为证据；公开 project 也必须经过 evaluate | 不存在槽位不能生成空引用；正常约束原样保留 |
| B3 缺证豁免 | 禁用 residual_accepted=true；实质缺证须补标 | 旧全量 residual 绕过失败；同义映射正控可通过，错误片段/词元/身份/缺证声明被拒 |
| B4 引文与元数据分离 | 覆盖只看 quote；搜索仍可用 metadata；search_hint/非首选提升须显式改选 + anchor_review | 82.9% 不再显示统计窗口完整覆盖；元数据不能顶替脚注；合法改选可通过 |
| B5 审批记录完整性 | 拒绝重复/未知身份、错题/错要件、负例缺依据及非法 chosen | 对应单项变异均阻断，正常正控仍可通过 |
| 投影后置校验 | quote/source/locator/constraints 必须与冻结 source-gold 一致；保留原审批记录以便审计 | 空引文、伪引文、错误来源、空定位均拒绝；不能绕过 evaluate 直接生成批准投影 |
| I3-5 衔接 | 任务表明确答案约束登记/投影保真门及测试资产 | 本轮零模型验证约束传递，不宣称真实生成答案的语义已验收 |

`lexical_review` 不是模型或算法的语义证明：人工必须把当前 facet、未覆盖词元逐项映射到 chosen 原文子串并给出理由，声明事实完整且没有实质缺证。机器核验身份、范围、引用真实性和映射集合；**是否确属同义仍由具名人工负责**。该机制不授权通过编造同义解释降低金标要求。

检索线索改选通过 `anchor_review` 单独记录，并不能免除缺词时的 `lexical_review`。不同来源的义务不能靠改选相互替代。真实缺少原文承载时仍须新 source-gold 版本，不允许用审批理由删除义务。

## 执行证据

- [red.txt](red.txt)：修复前 **10 failed / 57 passed**（新增10个缺陷反例红灯，新增1个正控和旧56项通过）。
- [green.txt](green.txt)：修复后 **88 passed**，包括32个审批/映射回归用例与原有56项评分器测试；其中还调用既有16条审批探针，全部通过。
- [green-final.txt](green-final.txt)：冻结前再次执行同一回归门；不以先前绿灯替代当前代码验证。
- [review-replay.json](review-replay.json)：上轮三个真实材料集合上的合成绕过全部 `ready=false`，直接生成投影也被拒绝；Markdown 重放一致。合成审批只在内存，不是真实人工签认。
- [i3s2_evidence_targets.txt](i3s2_evidence_targets.txt)：生成新版候选和裁决模板；原产物先归档再生成。
- [i3s2_apply_decisions.txt](i3s2_apply_decisions.txt)：实际命令消费路径确认无审批件，未生成 approved。
- [i3s2_verify_candidates.txt](i3s2_verify_candidates.txt)：30题自洽检查0失败、旧探针16/16、真实完整性门保持关闭。
- 定向 Ruff `E9,F,I` 与所修改工具/审计脚本的格式检查通过；未将项目全量测试或真实 PG 链路宣称为已重跑。
- 未运行会产生模型调用的 preflight：本轮零模型约束保持不变。

复现命令（仓库根目录，使用已有 `.venv`，不安装依赖）：

```bash
.venv/bin/python -B .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remediation/run_checks.py <新的日志名>
.venv/bin/python -B .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py
```

测试 runner 内部清空非必需环境变量、禁用 pytest 自动插件，并启用 I3 守卫；日志 write-once。旧复验脚本保留原字节，不直接重跑覆盖其历史输出。

## 材料变化与冻结边界

- 仍为30题、54目标：required35 / supplementary4 / suggested15；状态2 machine_ready / 20 pending_human / 2 blocked / 6负例；待裁决40 + 整题24 + 负例6 + 状态澄清1。
- 原文词面覆盖重算后，部分覆盖锚点从9增至13。这是纠正 metadata 造成的虚假完整覆盖，**没有减少原题要求、也没有增加或伪造源事实**。
- 修复了旧合成正控夹具自身的错位：建议 item_index=0 原本指数字而非条件，应为1；“门槛”原本只在 text 元数据，现把完整条件放进合成 quote。只改测试夹具，不改真实 source-gold。
- `before-r24/` 按 r24 哈希保留修改前工具、产物、两份台账和验证器原字节。旧 r1—r24 快照不改写；r25 只在 manifest 追加条目并显式重绑范围内路径。
- `I3-5` 本轮只补定义与局部契约测试；完整 I3-5 的检索/财务等非回归仍需在其阶段按最终资产重跑。真正生成答案的语义验收为 **not_run**，若要执行须另定输入、人工判据和有限预算。

## 接下来需要谁做什么

工程侧五类修复已交付，下一步可独立复核本轮改动及原文映射协议。U 的真实裁决仍不能由程序代替：尤其 macro-003/macro-004 等无承载项，以及其他部分覆盖锚点，须确认是否已有合适原文；缺失则先补来源标注，再形成新版本并审批。

不应直接填写 residual=true，也不应因为回归通过而批量签认全部题目。本轮绿灯只证明已锁住所列工程边界，不证明54个候选已成为完备金标。
