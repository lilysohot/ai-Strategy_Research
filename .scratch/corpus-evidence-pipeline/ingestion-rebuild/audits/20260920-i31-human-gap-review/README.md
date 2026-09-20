# I3-1 人工判级入口（i0c-r36）

状态：机制已实现；真实人工判级待签署。I3-1 / M6 未完成，不能据本轮测试把
`per_class_min_2` 改为 true。用户本轮的“方案 A”指人工判级，不是旧解卡文档中
编号为 A 的追加干净来源；本轮未追加、撤换或发布任何真实材料。

## 契约与实现

- `human-gap-review-1` 绑定 source_id、build_id、完整 build 指纹及 gap-policy-2。
  完整指纹包括准入决定、各 rev、scope、质量台账等全部 Build 字段。
- reviewer、带时区 reviewed_at、scope_rationale、evidence_scope_ref、完整
  required_locators、逐缺口 rationale 与明确 attestation 均必填。审核人同时签认
  目标证据集合完整，并确认逐处核对原始内容；代码不从检索结果自动挑一个容易通过的集合。
- 内容哈希不是密码学签名。与 admission 一样，凭证来源是受信任的人类操作入口；
  本轮不声称已验证外部身份服务或自动证明“目标集合语义完整”。
- 登记及发布/check/status 同源重验。不完整、错误/陈旧绑定、未知码、重复字段、
  未保留证据、同页/字符重叠或无法比较的坐标均拒绝。
- 默认分级表未改。只改变该 build 的 lifecycle，disposition、原始区域状态、
  原文、单元/块、quality_report、scope_ref 均不改。coverage 保持 scoped/unknown。
- 复用现有 corpus_source_checkpoints 中的专用不可覆盖命名空间；没有 DDL 迁移。
  普通检查点 API 拒绝写入该命名空间；专用登记同内容幂等、异内容冲突。
  每个 build 必须一次提交所有仍 blocking 缺口的完整凭证。草稿可在登记前修改；
  登记后更改裁决须退役旧发布、以新构建/准入身份重审。
- 发布记录保存 human_gap_review_id。发布重试/回滚仍查凭证，缺失/损坏不得沿用旧成功。

## 人工接续

四份模板来自现有隔离 PG 的批准开发 build，只包含客观绑定与空待填写字段：

| 模板 | 来源 | 待核验缺口 |
|---|---|---:|
| [unsigned-6f14cc14.json](unsigned-6f14cc14.json) | 华创·贵州茅台 | 1 |
| [unsigned-dddc7cd0.json](unsigned-dddc7cd0.json) | 国信·光力科技 | 1 |
| [unsigned-174b6462.json](unsigned-174b6462.json) | 长江·化工十问十答 | 10 |
| [unsigned-793b3967.json](unsigned-793b3967.json) | 光大·美国非农 | 1 |

复制模板到新的签署文件，保留本目录空模板作为审计证据。审核人核对原始来源和该 build
获批所需证据全集后填写空字段；`required_locators` 首版支持 `page:N`、`char:a-b`。
只有完成核验才能填写 `attestation=human_verified_complete_scope_and_nonintersection`。
将所依据的批准范围记录引用填入 evidence_scope_ref，完整性说明填入 scope_rationale。
这些字段由人签认，不是系统默认填充的“批准”。

光力 p7 是已知反例：缺口为整页 page:7，金标也引用 p7。当前坐标不能证明不相交，
即使具名签署也拒绝。不得删掉 p7 的目标 locator 或凭空改小缺口范围来满足门。
其它缺口同样要实际逐处核验，不能预先承诺 13/13 全部通过。

在既有 i3-e2e 守卫环境中使用（不在无守卫进程直接连接 PG）：

```bash
uv run python -m plugins.corpus.cli gap-review --build <build_id>
uv run python -m plugins.corpus.cli gap-review --build <build_id> --record <new-signed.json>
uv run python -m plugins.corpus.cli check --build <build_id>
uv run python -m plugins.corpus.cli publish --build <build_id> --operator <operator>
```

签署、登记、发布之后，才可对批准的 8 份材料重跑逐类计数、格式门与取证审计。
当前 4/8 可发布、13 处阻断的历史实测没有被改写。

## 验证与冻结

- [常驻反例测试](../../../../../tests/test_corpus_gap_review.py)：真实合成 PDF 读取器→build→
  发布，及空凭证、重叠/不可比、错绑定、篡改/重复、不可覆盖、CLI 视图与发布重试。
- [PG 核验](pg-verification.json)：在现有隔离库中使用只回滚事务，合成读写/发布/coverage
  通过、residue=0；真实凭证登记与真实发布均为 0。
- `run_checks.py` 运行受影响 preparation/CLI/scoring 回归。准入测试读取既有获批材料，
  使用原 i3-e2e 守卫；守卫自测自行在子进程装载各自配置，避免把父进程守卫重复装载。
- 新人工判级反例另在原 i3 守卫（无网络/无来源读取）下运行。
- `archive_r36.py` 在所有改动前调用 archive_first，归档 10 条路径并按冻结验证器实际
  生效顺序核对旧绑定。`freeze_r36.py` 绑定新实现、测试、文档、审计及真实 pre-r36 字节，
  parent=i0c-r35。守卫、gold、准入政策、旧修订与旧审计产物字节不变。
- 通用 preflight.py 会调用模型，依本任务零模型边界不执行；不将其记为通过。
- 通用 import_smoke --stage 1/2 在原 i3 守卫下实跑，被模型 SDK / `_r2_*` 禁止导入
  规则拒绝；日志保留为 `import-smoke-stage-*.txt`，不记作通过，也未卸载守卫绕行。
