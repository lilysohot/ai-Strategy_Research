# 金标集回溯核查（issue 35 · material_items 48 条）

## 一、记账核验
- frozen-gold：status=frozen、frozen_on=2026-10-08、reviewer/adjudicator=xyl/xyl
- freeze-state：quality_gate_passed=False、candidate_execution_authorized=True
- freeze-manifest：quality_gate_passed=False，输入哈希逐项核验 7/8 匹配
- validation-report：status=valid_review_draft、errors=[]、human_accepted_counts={}
- 契约绑定：记录 `sha256:2eb24be7e74f9e6003ca623487478790cdb60265c5f05377eda377f498f3bdbe` vs 实际 `sha256:d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce`（match=False）

## 二、48 条逐项结论摘要
- review_status 分布：{'accepted': 48}；adjudication 非空：48/48
- critical 12、risk_or_condition 21、condition 角色 10
- 原文可逐字回取（locator+start/end 与 quote 完全一致）：48/48
  不可逐字回取的记录：[]
- 落在候选 scope 内：48/48；触碰丢失 unit：7
- 缺契约必需字段的记录：0/48，缺失字段=[]
- condition 角色但无 condition 字段：[]
- 候选侧逐字命中（quote 与某候选 evidence_quote 互相包含）：39/48

## 三、条件组与丢失包
- opening_watch_position：['NT-I42', 'NT-I13', 'NT-I43'] → NT-I14；locator=char:5246-5537；触碰丢失 unit=True；其中 critical=['NT-I13', 'NT-I14', 'NT-I42', 'NT-I43']
- stop_loss：['NT-I15', 'NT-I17'] → NT-I16；locator=char:5246-5537；触碰丢失 unit=True；其中 critical=['NT-I15', 'NT-I16', 'NT-I17']

## 四、供人工核查的文件清单（含 sha256）
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json` — 48 条非表格金标（material_items 切片在本审计中核验）
  - sha256：sha256:603de5e6c532463db8ae2788b830c2c1a74400b4ba736292bd5503468dfa7de2
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-freeze-20261008-r2/freeze-state.json` — 冻结状态与授权来源
  - sha256：sha256:08703b8dad9fc6c130872899741534c940787c29a15423db19d398999b237d85
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-freeze-20261008-r2/freeze-manifest.json` — 冻结清单与输入哈希（含 quality_gate_passed 标记）
  - sha256：sha256:da85e29397f1b4b45186567079a9f2341bf36e42b7bf2ba8cb7102b23632b23e
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-freeze-20261008-r2/freeze_signed_gold.py` — 冻结脚本（生成 frozen-gold 的代码）
  - sha256：sha256:80e6453018edfb23b9fe9444ad4df40461f02d785134ebb1271a27201469c6b6
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/gold-review-candidates.json` — 人工评审草稿（含逐条 review_status/adjudication 的原始录入）
  - sha256：sha256:f8feaf96168c1a068d6e0c0e1a1f6b34113765ed5a76058c3d9f02ea730ccc59
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/gold-review.md` — 由 JSON 生成的评审可读稿（1616 行，可逐条对照）
  - sha256：sha256:71cac53f319d5f6cd940840819cb8dd35765f685b4ab24437d066eabd74e563b
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/validation-report.json` — 机械校验报告（human_accepted_counts 现状见审计结论）
  - sha256：sha256:139cfc222eb4688dccdce5c0116b00c84b87401e01e22427658c3dcfa6d5bc52
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/draft-manifest.json` — 草稿清单与输入哈希
  - sha256：sha256:e8cd173761d2908864fa90388e2910462cca8f87901e0618f5f1fd9ab88fa87b
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json` — 评分契约 v3（当前签认版本）
  - sha256：sha256:d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r2/review_pack.py` — 评审包生成脚本
  - sha256：sha256:fe5c84587873b1032c3c3b2a6b5acf4b16f4c53090b37c924c9915374b06eb81
- `.scratch/claims-r2-role-isolation/evidence/10-quality-gold-expansion-20261008-r1/source-prose-units.json` — 候选输入范围的源单元导出（locator/文本哈希）
  - sha256：sha256:58aa7c997376c9d7f5a84766725cf2fadddc649c7e9f73ff7309727048a37436
- `data/corpus/工业富联_投委会决策报告_20260829.md` — md 源文件（人工回取原文用）
  - sha256：sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb

## 五、本审计的产物
- `gold-audit.json`（逐条明细，含每条 quote 的 resolved span 对照）
- `gold-audit.md`（本文件）
