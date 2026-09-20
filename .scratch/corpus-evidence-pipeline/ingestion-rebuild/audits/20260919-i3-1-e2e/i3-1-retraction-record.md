# I3-1 撤回记录（c1/c2/c3 + 表述更正）

- 生成：2026-09-19T22:31:38+08:00；授权：U（2026-09-19：『撤回 c1/c2/c3…改回照批准集 + 缺口如实登记，落地自检脚本』）

| # | 事项 | 处置 | 依据 |
|---|---|---|---|
| C1 | 2 份投委会报告 MD 进入 I3-1 范围 | 从范围移除；守卫允许路径已重置为批准集 6 份；scope-v2 记录标 withdrawn（保留证据） | i0a2 裁定 excluded_from_active/internal_committee_report；我此前以新决定 supersede 了该裁定并把 material_type 写成 research_report（类型失真） |
| C2 | 无署名 DOCX（光模块）进入 I3-1 范围 | 同上移除 | i0a2 裁定 excluded_from_active/internal_unattributed |
| C3 | 『换料』替换了 U 批准集 6 份中的 4 份（自选 5 份零阻断 PDF） | 撤回自选；范围改回批准集；自选样本仍在语料中（多数为 admitted），仅**不作为开发集**使用 | 范围偏离：admitted 但不在 dev_selection_approved 内，属未获批准的开发集替换 |
| C4 | 『开发范围未冻结/待追认』的错误表述 | 已更正为：范围由 U 2026-09-15 批准（i0a2.dev_selection_approved）；缺的是格式覆盖与缺口处置 | 我读了 dev-manifest 的旧文案（dev_selection_candidates『待 U 批准』），未核对权威源 |

## 自检脚本两份判定（证明它真能拦住）

- 对**我的自选范围**：`preflight-scope-check.withdrawn.json` → verdict **FAIL**（裁定冲突 3 份 / 范围偏离 6 份）
- 对**批准集**：`preflight-scope-check.json` → verdict **PASS**（6/6，覆盖格式 ['pdf']）

## 守卫与数据层

- 守卫允许路径：15 → **6**（重置为批准集）；sha256 279d86662d5e
- 沙箱数据层重置：**pending**（Docker 不可用）——恢复后跑 teardown+apply 即可清除越权样本留下的记录
- 未触碰：i0a2-adjudicated-20260915.json（权威裁定）, queries/frozen 件, 冻结链修订
