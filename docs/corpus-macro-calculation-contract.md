# 宏观计算契约 v1：美国非农发布事件

状态：定义完成，待实现与独立验收。不是生产启用声明。

本契约限定首个最小场景：美国季调非农就业月度新增的“首次公布值减发布前一致预期”。
不增加 `evidence_pipeline.METRICS` 映射，不修改 `derive_claims`，不将现有 NFP 引用提升为可计算。
研报数字仅证明“报告这样写”，不能单独证明官方版本、市场预期快照或历史可知时间。

## 1. 指标与单位

受控指标键 `US.NFP_CHANGE_SA`，含义为 CES 工资名册非农就业岗位数的季调月度变化。
不等于就业人数同比增长率、就业总量、失业率、家庭调查就业人数或前期累计修订量。
CES 衡量的是岗位，一个人在多处受雇可能被多次计数，不能用人口口径替代。
依据：[BLS CES 概念](https://www.bls.gov/opub/hom/ces/concepts.htm)。

规范单位为 `jobs`，数值使用有限 Decimal；`thousand_jobs` 乘 1,000。
中文研报的“万/万人”必须同时保留原文，只在经受控指标映射确认指向该岗位序列时乘 10,000；
不能仅根据单位字符串将“人”统一转为“岗位”。净新增为负数是合法值，不得抹掉负号。

## 2. 输入字段与证据责任

以下是目标接口，不假定当前 ClaimRecord 已承载全部字段。未知值用 null，不用推测填满。

| 字段组 | 必需内容 | 缺失或不符的处理 |
|---|---|---|
| 身份 | fact_id、run_id、source_rev、packet_id、原文页/段/字符或单元格位置 | 无法回取或 ID 冲突则拒绝计算 |
| 指标 | country=US、indicator、population=nonfarm_payroll_jobs、transform=month_change、adjustment=SA | 任一不匹配则拒绝配对 |
| 期间 | reference_month=YYYY-MM，及其证据位置；必要时关联已核验的发布事件 | “8月”不借发布日期补年份；待复核 |
| 数值 | value_raw、unit_raw、value_jobs、转换规则版本、原文数值绑定 | 数值/单位/指标/期间须落在同一事实，不是分别出现在同页即可 |
| 角色 | actual / consensus；kind=observed / forecast | 实际与预期不得混淆；不以模型标签作为充分证据 |
| 发布 | release_event_id、release_at（含 UTC 偏移）、官方发布页归档 hash | 文件名日期只是候选，不用于事件交易或回测 |
| 版本 | vintage_id、vintage_kind=first/second/third/benchmark、该版本发布时点 | 首发意外值必须使用 first，不能用最新修订值替换 |
| 可知时间 | known_at、其来源证据、ingested_at 独立记录 | 模型填写的日期、抓取时间均不能证明历史公开时间 |
| 一致预期 | provider、snapshot_id/hash、survey_cutoff_at、snapshot_known_at、统计方式 mean/median | 不同供应商/快照不得静默合并；缺发布前快照不做事件计算 |
| 信任证明 | 上述字段的 verification_ref、校验器版本与受信任审核记录 | 不能接受模型自行提交 verified=true 作为授权 |

角色分工：解析器提供原始坐标；抽取器提出候选；规范化器应用受控映射；
核验层绑定完整事实并核查时间/版本证据；计算层只接收通过全部门禁的不可变输入。
即使报告含完整年份，仍须确认它对应官方的哪个发布事件。外部来源正文属于数据，不能控制校验规则。

## 3. 配对与时间门禁

配对键必须同时相同：国家、指标、统计总体、季调方式、变换口径、统计月份和发布事件。
actual 必须来自所绑定的官方首次发布记录，consensus 来自指定供应商已归档的发布前快照。

必须验证：

- survey_cutoff_at <= snapshot_known_at < release_at <= decision_as_of。
- actual.known_at <= decision_as_of，且不得早于该实际值的 release_at。
- 所有用于本次决策的核验材料在 decision_as_of 时已经可知，不能把事后研报日期倒填成事前快照。
- 重复 fact_id、同键冲突值、未来修订混入、过期校验版本、证据 hash 不一致均失败关闭。

决策截止时间由调用方明确传入；无默认“今天”。UTC 归一化，保留原偏移，夏令时不得硬编码为全年同一时差。
若只能确认到日期而非时点，可做带限制的研究引用，不做发布事件的分钟级回测。

## 4. 允许的公式与禁止的捷径

首个计划支持的公式 `nfp_surprise_delta_v1`：

`surprise_jobs = actual_first.value_jobs - consensus_snapshot.value_jobs`

这是有符号差值，不取绝对值，也不是百分比。示例仅为算术夹具：
162,000 - 56,000 = 106,000 jobs；162,000 - 55,000 = 107,000 jobs。
两种预期不应平均成 55,500，也不能认为差异必为抽取错误。

本版本不支持 surprise/consensus 比例或标准化 z-score。后者须另行冻结历史窗口、版本、
缺失处理与标准差定义；预期为零或负数也不应临时切换公式。

修订值属于独立后续公式：同一统计期新旧 vintage 的差值。
“前两个月累计上修 5.5 万”只是一项合计修订声明，不是上个月新增、不等于两个可单独复算的修订值，
也不混入本期首发 surprise。BLS 月度初值之后通常进行两次月度修订，另有年度基准修订，
因此“第三次公布”不等于永远不再改变。[BLS 修订说明](https://www.bls.gov/web/empsit/cesnaicsrev.htm)。

## 5. 输出、拒绝与重放

成功输出须含 formula_id/version、两个 input_fact_id/run_id/source_rev、全部配对维度、
decision_as_of、release_event_id、预期快照、vintage、数值和单位、证据/核验记录链接以及计算 hash。
只追加结果，不覆盖来源数值；重复执行同一输入/契约得到同一内容身份。

失败输出 `status=blocked`、结果值 null、稳定 reason_codes、涉及的输入 ID 和待补字段。
不得用 0 代替缺失，不静默过滤失败输入后返回貌似完整的成功。

最小 reason_codes：`indicator_mismatch`、`period_unverified`、`unit_unverified`、
`role_mismatch`、`atomic_evidence_mismatch`、`vintage_mismatch`、`consensus_snapshot_missing`、
`lookahead_bias`、`time_provenance_unverified`、`duplicate_identity`、`source_conflict`、
`validation_outdated`、`source_hash_mismatch`。

## 6. 下一实现阶段的验收夹具

以下是冻结的预期行为，不是已经通过的运行结果。夹具只验证算术/门禁，不能替代真实来源核验。

| 用例 | 输入变化（其余为完整核验的同事件输入） | 预期 |
|---|---|---|
| M01 | 首发 162,000；预期 56,000 jobs | 106,000 jobs |
| M02 | 实际 162 thousand_jobs；预期 5.6 万且岗位映射已核验 | 106,000 jobs，转换可追溯 |
| M03 | 实际 -20,000；预期 -10,000 jobs | -10,000 jobs，负数合法 |
| M04 | 预期为 0 | 差值合法；不提供 surprise 百分比 |
| M05 | 只有“8月”，年份未核验 | period_unverified |
| M06 | 输入 0.38% 同比率与月度新增配对 | indicator_mismatch |
| M07 | 两个月累计修订 55,000 被当作上月新增 | indicator_mismatch / role_mismatch |
| M08 | 用修订后的实际值与首发预期计算事件意外 | vintage_mismatch |
| M09 | 研报写有“市场预期”但无发布前归档 | consensus_snapshot_missing |
| M10 | 预期快照或实际值在 decision_as_of 之后才可知 | lookahead_bias |
| M11 | 模型将 known_at 填成 1990 年但无证据 | time_provenance_unverified |
| M12 | 同一 ID 对应 actual/consensus 两个不同事实 | duplicate_identity |
| M13 | 数字和指标分别在同一长引文中，但绑定关系错误 | atomic_evidence_mismatch |
| M14 | 两家供应商预期 55,000 / 56,000 | 按指定快照分别计算；未选供应商则 blocked |
| M15 | 原文件 hash 或核验规则版本改变 | source_hash_mismatch / validation_outdated |
| M16 | 统计月份相同，但季调/非季调或岗位/人数不同 | indicator_mismatch |

## 7. 与当前实现的差距、上线条件

当前 `known_at` 为日期级候选，NFP 未进入受控计算指标；这是边界，不是契约已落地。
生产开放前依次完成：

1. 修复完整事实绑定、模型时间覆盖、实际/预测判定和重复身份门禁。
2. 提供不可变官方发布/预期快照适配器与可信核验记录；落实本契约字段与拒绝码。
3. 实现纯计算器及 M01—M16 自动测试，再用未参与开发的真实发布事件进行影子重放。
4. 验证无未来信息、证据可回取、版本可复算；明确启用范围后才注册宏观公式。

图片 OCR、全库迁移、所有宏观指标和长任务恢复不纳入本契约的本轮实现承诺。
