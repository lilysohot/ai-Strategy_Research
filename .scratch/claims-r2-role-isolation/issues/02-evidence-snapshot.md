# 02 · 同源证据快照、必要语境与取证映射

Status: needs-triage
Execution: 未开始
Type: task
Plan: W1；R2-S1
Blocked by: 01
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

让 Claims 和 R2 从同一不可变证据快照取输入，保留可验证表格及必要限定，并能映射到当前原文 resolver 接受的坐标。

## 前置与外部门

01 已验收；确认 R2-S1 的 S0/I1 前置，不把合成快照通过冒充真实来源准入。数据库读取用内存/录制 Adapter；真实 PG 集成验证另经环境门，不在本票连接生产库。

## 范围与预期文件

- plugins/corpus/service.py、evidence_pipeline.py、material_semantics.py 的输入接缝；优先复用 preparation/read_pg.py、现有表格/cell 结构，不重写解析器。
- 快照实现固定落在 `plugins/corpus/structured/snapshot.py::build_snapshot`，输出遵守
  `contracts/v1/evidence-snapshot.schema.json`；tests/test_corpus_structured_snapshot.py 与合成 fixtures。
- 精确绑定 source/build/publication、units/cells/坐标、解析缺口、包清单及规则版本，先封存后调度。
- 在包/条目中记录必要标题、指代、条件、否定、表头和脚注依赖；未知依赖不猜补。

## 验收条件

- [ ] 活动 build/publication 切换期间，只产生一致快照或调用前失败；同文字但位置/类型变化会改变指纹。
- [ ] 两路可取不同候选子集但共用快照；R2 启动不要求 Claims facts 成功，旧文件独立解析不被当作新默认输入。
- [ ] 完整表格进入 Claims table 分支；R2 所需脚注/说明不因 table 类型被静默跳过。
- [ ] 包外“仅在并购完成情况下”能关联原文依赖；歧义、缺失、超预算时给出明确降级与定位，不能发布为无条件可计算预测。
- [ ] 每段发布候选可映射为 cv2:<build_id>、chunk:<chunk_id> 和准确 unit/cell/quote 区间；拒绝将 source_id 当 build_id。
- [ ] 重复引文、复合证据和续表不靠首次字符串命中/最近文本猜测；不同片段保留各自句柄。
- [ ] 现有业务字段/历史读取契约回归通过，未改变基础入库成功条件。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_snapshot.py tests/test_corpus_evidence_pipeline.py tests/test_corpus_material_semantics.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_snapshot.py
```

新增快照测试须通过注入只读 Adapter 覆盖版本切换，不依赖真实 DB。

## 非目标

不新增 OCR、视觉/解析供应商，不无差别重建来源，不保证确定性规则发现所有隐含语义遗漏。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
