# I3-1 格式覆盖探针（U 补的 DOCX / MD）

- 生成：2026-09-19T18:59:07+08:00；问题：U 补的 DOCX 能否使『格式门』通过？MD（投委会报告）同理
- 政策规则：admission.py 次序 2：admitted 且 material_type ∉ {research_report, unknown} → POLICY_CONFLICT → REVIEW_REQUIRED；仅 research_report 才 IN_SCOPE
- DOCX：`data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx`（25406 字节，sha256 48c05895798b）

## 口径 A：不给材料类型凭证（真实政策判定）

| 来源 | decision | reason_codes | material_type | build_id |
|---|---|---|---|---|
| 9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx | **in_scope** | None | None | e3fa3cb577dad2130566e86e28f90eb069c8cc9cbe3a6a7878c04124a29d52cf |
| 仕佳光子_投委会决策报告_20260831.md | **review_required** | None | None | None |

## 口径 B（对照，未获追认）：假设 U 认定该 DOCX 为分析师研报

- 取代链：`i3e2e-docx-21b0e21e` → `i3e2e-docx-21b0e21e-whatif`
- DOCX：decision=in_scope，build_id=cd7bf18dc6ffabe2e24d6762e28708dc3f502ae9e85b6cf17d9cfb6ab11b1325，单元 44 / 切块 7
- check：exit=0，publishable=True
- 缺口：[]
- publish：{"exit_code": 0, "generation": 1}

## 结论（需要 U 的动作）

- **docx_under_policy_v1_without_credential**：见 pass_a：预期 REVIEW_REQUIRED（POLICY_CONFLICT）
- **docx_pipeline_if_admitted**：见 pass_b_whatif：DOCX 管道自身能否出版=看 check
- **what_U_must_decide**：① 该 DOCX 的材料类型是否为『分析师研报』（人工凭证，只有你能给）；② 若不是：要么换一份 analyst 类 DOCX，要么批准准入政策 v2（放宽格式/类型）并重跑政策验证
- **md_note**：MD（投委会报告=internal_committee_report）同理；本轮未做 MD 的对照口径

## 口径 A 的 DOCX 也过了门（无材料类型凭证）

- check：exit=0，publishable=True，缺口=[]
- publish：{"exit_code": 0, "generation": 2}
- 沙箱审计计数：{"sources": 8, "admissions": 8, "builds": 14, "units": 8698, "chunks": 1548, "active": 3}；冲突 []
