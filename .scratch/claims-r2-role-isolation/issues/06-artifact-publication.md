# 06 · 工件保存、语义发布与跨运行回读

Status: needs-triage
Execution: 未开始
Type: task
Plan: W3；R2-S2/S3（文件试点，不代表生产 S5）
Blocked by: 05
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

让合格角色结果经受控文件 Adapter 发布，并在另一研究运行中可发现、核验和读取；独立发布与后到冲突不破坏版本一致性。

## 前置与外部门

05 已验收，01 已固定根目录配置键/索引结构/发布写入策略。仅写测试临时目录或明确实验输出；不迁移生产数据库，不修改旧 corpus_evidence_runs。

## 范围与预期文件

- 文件 store/发布固定落在 `plugins/corpus/structured/store.py`；不可变对象在
  `objects/sha256/`，发布 manifest 在 `manifests/`，权威 head/generation 在
  `index/structured.sqlite3`，`cache/heads/` 仅为可重建缓存。角色校验使用 v1 contract。
- tests/test_corpus_structured_store.py、tests/test_corpus_structured_publication.py。
- 不可变 raw/角色工件、校验和、执行账引用、逐角色覆盖和语义发布 manifest；研究消费账/报告清单不存入此目录。
- 跨角色映射区分确定对应、疑似、未关联和字段冲突；规则版本与证据绑定。

## 验收条件

- [ ] 同一输入的不同模型运行保留独立身份；文件存在不等于发布，旧加载器不能成为新 JSON 回读路径。
- [ ] 精确引用、原文依赖与用途检查通过才进入可用清单；未关联不算一致，同 locator 多命题不误合并。
- [ ] Claims 可先发布 P1，R2 后到冲突发布 P2 收紧受影响用途；失效 items 的关系不能继续以有效状态提供。
- [ ] 首轮单发布写入者或已冻结的父版本检查生效，双路提交无丢更新；断电/崩溃不暴露半份清单，历史可诊断复现。
- [ ] 来源更新、规则升级、撤回与过期分开处理；不以“最新一次失败”覆盖旧合格历史，更不能把旧结果当新 build。
- [ ] 关闭写端、切换 cwd 和研究 run 后可按配置根目录和发布索引读取；不依赖内存对象/临时 cwd，不全盘搜索。
- [ ] 缺目录、权限不足、损坏哈希、未知 schema、未发布和撤回分别报错；检查零模型、无自动重抽。
- [ ] 路径解析限制在配置根目录，工件引用不允许越界；读端不获得后台写权限，不泄露 raw 密钥信息。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_store.py tests/test_corpus_structured_publication.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_store.py tests/test_corpus_structured_publication.py
```

必须包含两个进程/两个 cwd 的真实文件回读测试、发布竞态和损坏工件反例，不能仅复用进程内字典。

## 非目标

不恢复旧 evidence 表，不将 JSON 试点冒充生产 PG 保存，不修改来源正文或建设全库缓存治理。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
