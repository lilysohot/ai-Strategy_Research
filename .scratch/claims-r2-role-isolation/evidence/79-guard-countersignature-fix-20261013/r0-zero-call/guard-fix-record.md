# 护栏第三处机制误报修复：`countersignature` 占位被误判为已签（零模型调用）

- 2026-10-13　只读工作树（除本目录输出）；写入经共享护栏 `write_once`

## 一、缺陷

- 位置：`tools/evidence_guard.py::artifact_state` — `for key in _COUNTERSIGNATURE_KEYS: elif payload.get(key): return "signed"`
- 现象：只要 countersignature 键非空即判 signed，不区分占位与签署
- 触发件：`.scratch/claims-r2-role-isolation/evidence/74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/gate-v3.proposed.json`（自带 `status=draft_pending_human_signature`，`countersignature={"required": true, "status": "pending_human_signoff", "reviewer": null, "signed_on": null}` ⇒ **未签草案**）
- 可观测：tools/check_evidence_guard.py exit=1，violations=1，报 evidence/74-…/build_r2_drafts.py -> ['gate-v3.proposed.json']

## 二、根因（不是脚本缺护栏，而是护栏误判）

- **same_class_as**：evidence_guard.py:101-102 自陈：仅凭 signoff 键存在即判已签，曾把 v4.2 草案误判为已签（2026-10-12 发现）
- **incomplete_fix**：2026-10-12 只修了 signoff（_signoff_block_filled），countersignature 仍为「键存在即判签」
- **already_reported_unfixed**：evidence/76-r2-retro-audit-20261013 §四第 4 行（artifact_state 把未签门草案读成 signed，已上报、未修、待另裁）

## 三、修复

- 判据：_countersignature_filled()：显式签署证据（signed_by / instrument / signed_on）一律判 signed；状态属 _PENDING_SIGNOFF_STATUSES 时判未签；其余形态一律维持 signed
- 保守性：未知状态、缺状态、非 dict 非空值都仍按 signed 保护；本次不存在任何「真签件被判 plain」的变化
- 待签状态集：awaiting_signature, awaiting_signoff, draft_pending_human_signature, not_signed, pending, pending_human_signature, pending_human_signoff, pending_signoff, proposed_pending_signoff, unsigned
- 影响范围：只影响 countersignature 一个键；signoff 语义（空块=未签）原样保留

## 四、影响面（全树扫描，修复前 vs 修复后）

- 扫描 JSON 产物 2863 个；状态变化 **1** 个：

| 文件 | 修复前 | 修复后 |
|---|---|---|
| `74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/gate-v3.proposed.json` | signed | plain |

- 只有处于**显式待签状态**的 countersignature 占位块会被重新判为 plain；其余形态（含未知状态）一律维持 signed（fail-closed）。

## 五、保护未削弱（关键签认件逐一复核）

| 产物 | 状态 |
|---|---|
| `75-r2-signed-20261013/r0-zero-call/gate-v3.json` | signed |
| `75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json` | signed |
| `58-contract-v42-signed-20261012/r0-zero-call/scoring-contract-v4.2.json` | signed |
| `10-quality-gold-freeze-20261008-r2/frozen-gold.json` | signed |
| `28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json` | signed |
| `74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/gate-v3.proposed.json` | plain |

- `signed_targets_protected` 保持 9（与修复前一致）。

## 六、验证

| 项 | 命令 | 退出码 | 结果 |
|---|---|---|---|
| P06 护栏测试 | `uv run python -m pytest -q tests/test_evidence_guard.py` | 0 | 24 passed in <elapsed> |
| 证据守卫扫描 | `uv run python tools/check_evidence_guard.py` | 0 | violations=0 / guarded=9 / legacy_exempt=4 / signed_targets_protected=9 |
| 冻结链校验器 | `uv run python tools/check_freeze_chain.py` | 0 | ok=16 covered=8 drift=0 needs_ruling=0 |
| ruff | `uv run ruff check tools/evidence_guard.py tests/test_evidence_guard.py` | 0 | All checks passed! |

## 七、保留项与未做项

- **保留**（proposed_pending_signoff_in_SIGNED_STATUSES）：保守保留：它是「已发出待签」的提案态，覆盖它会使待签件失效（fail-closed）。移出该集合属放宽保护，须用户另行裁定。
- 未做：未把 evidence/74-…/build_r2_drafts.py 登记进 evidence_guard_exceptions.json（登记理由不成立：该脚本产物是草案而非已签产物，登记会封存误报）
- 未做：未修改任何 evidence 产物字节；未重跑任何历史脚本
- 未做：未改动 evidence/76-… 的字节（其上报的行由本记录声明已解决）

## 八、复现

```bash
uv run python .scratch/claims-r2-role-isolation/evidence/79-guard-countersignature-fix-20261013/r0-zero-call/build_guard_fix_record.py
uv run python tools/check_evidence_guard.py
```
