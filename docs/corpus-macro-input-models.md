# M1 宏观输入模型与审核记录

版本：`macro-input-1`；单位转换版本：`nfp-jobs-1`。
范围：输入结构、证据身份、审核记录与受控单位换算。不是宏观数据已验证或计算已启用的声明。

## 类型与身份

| 类型 | 记录内容 | 主要约束 |
|---|---|---|
| ReleaseEvent | 发布方、发布事件键、统计月份、发布时间、归档位置/hash、逐字段证据 | 未知月份/发布时间保留 null；归档声明不等于已核验 |
| Vintage | 发布事件 ID、统计月份、first/second/third/benchmark、版本公开时间、前版本 ID | 不把首发和修订混成同一身份 |
| ConsensusSnapshot | 供应商、事件/月、mean/median、调查截止、快照可知时间、归档证据 | 缺失供应商/快照时间不默认补齐，不跨供应商平均 |
| MacroObservation | 显式统计维度、actual/consensus、observed/forecast、原值/单位、关联版本/快照、可知和入库时间 | actual 对应 observed，consensus 对应 forecast；角色不靠指标名隐含；不接受自带 verified |
| VerificationRecord | 审核对象 ID、审核方与角色、策略版本、审核时点、审核范围、原文引用、决定与拒绝码 | 格式合法不产生信任；审核对象为完整内容身份，不只绑定一个数字 |
| BlockedInput | 输入 ID、blocked、null 结果、稳定原因码、待补字段 | 不用 0 代替缺失，不允许无原因的 blocked |

所有模型为冻结 Pydantic 类型，拒绝额外字段。嵌套结构只使用冻结模型和 tuple，不含可变 dict/list。
`model_copy(update=...)` 重新校验，不使用 Pydantic 默认跳过校验的更新捷径。
身份与角色属于最低结构要求；无法提供这些必填信息时应使用 BlockedInput 记录缺失，而不是猜测角色。

`record_id` 从完整 JSON 内容计算 SHA-256，包含 schema_version、record_type 和所有原始字段。
kind、qualifier、vintage、快照供应商或时间变化都会产生新身份。
`to_json()` 输出 `{record_id, payload}`；`load_record()` 同时检查结构、哈希、重复 JSON 字段。
`index_unique()` 对相同 ID 的重复输入直接拒绝，即使两条内容相同也不静默取最后一条。
未知 envelope/payload 字段，包括 verified=true，均被拒绝。

源字符表示也是内容的一部分，例如 `16.20` 与 `16.2`、不同源 UTC 偏移写法可有不同 ID；
不为了合并身份丢弃原文精度或时区。相同序列化内容重复加载的身份与输出稳定。

## 证据和时间

`EvidenceReference` 复用现有 run_id、source_rev、packet_id、locator、原始引文及字符起止位置，
可附 fact_id 与表格单元格引用。`EvidenceBinding` 显式标记该引用用于哪个字段。

- `reference_from_run()` 从现有 EvidenceRun 构造唯一、精确可回取的引文位置。
- `resolve_reference()` 校验 run 内容身份、源版本、包、位置、引文，以及可选事实/单元格是否存在。
- 这两项检查定位和内容一致性，不声称引文已经证明所有金融语义。语义核验和时序配对是 M2—M4 的责任。
- 旧 EvidenceRun 无需新增字段、不修改原 JSON、不重写原 run_id，也不提升旧运行的计算许可。

`SourceTime.raw` 要求明确日期、时分秒及 UTC 偏移，保留原偏移；通过 `.utc` 统一比较。
纯日期、无时区时间、非法日期和数值时间戳不能冒充精确公开时点。
release_at、published_at、known_at、ingested_at、survey_cutoff_at、snapshot_known_at 均独立保存；
未知字段为 null，不由入库时间、文档文件名或当前时间补齐。
M1 不执行事件配对的先后时序判断，这部分仍由 M4 完成。

## 信任入口：审核记录不是“自证清白”的 JSON

`VerificationAuthority` 只能由可信应用代码配置和调用，明确 issuer_id、issuer_role、policy_version 与
现有证据解析函数。`issue()` 校验证据可回取后，将审核者的决定登记成不可变审核记录；
`accepts()` 仅认可本 authority 已登记、对象 ID 相同、范围充分且获批的记录。

以下均不构成可信审核：

- LLM 提供 verified=true、任意 verification_ref 或“管理员”名称。
- 仅通过 VerificationRecord 的结构校验或内容 hash 校验。
- 把其他对象的审核 ID 复制到改过数值/单位/口径的输入。
- 用只审核 indicator 的记录代替完整 indicator + unit_mapping 审核。
- 将 rejected/unknown 的审核决定当作 approved。

**信任范围必须明确：**此 authority 是应用内部的内存登记，不是用户认证、数字签名、数据库权限或持久审计系统。
真实审核判断和调用者认证由宿主负责；M1 不会从字符串标签推断审核者的身份。
它不防御能够执行任意 Python 或修改同进程私有状态的恶意代码。
无外部 JSON 导入“可信记录”的接口，没有 Agent 工具或 CLI 暴露 issue()。
进程重启后登记为空；反序列化旧审核记录只恢复审计内容，不恢复信任。持久核验登记及认证接入留待后续，
不得通过“直接把 JSON 放回字典”绕过这项默认拒绝。

因此，M1 的“可信核验记录模型完成”不等于实际研报字段已审核、跨进程信任链已部署或 M4 已完成。

## 单位换算

`RawAmount` 原样保存 value_raw/unit_raw；仅解析完整、合法的有限十进制字符串，不从长句抽数，
不吞掉负号、不接受 NaN/Infinity，不把错误逗号或空值转成 0。

`normalize_jobs()` 当前只接受完整一致的 `US.NFP_CHANGE_SA` 岗位/月度变化/SA 维度：

- jobs → ×1；thousand_jobs → ×1,000。
- 万/万人 → ×10,000，必须提供绑定当前对象、由应用 authority 登记、覆盖 indicator 与 unit_mapping 的批准记录。
- 人口口径、同比率、修订合计、NSA、缺失维度及未经解释的 qualifiers 均不转成该岗位指标。
- 百分号不能凭一张审核记录转换成岗位数。

返回原始字段、value_jobs、转换版本、审核引用和原因码；Decimal 换算不依赖外部默认精度。
成功只表示单位标准化，`calculation_permitted` 永远为 false。
规范化成功不代表官方实际值、预期快照、统计年份、数据版本和公开时间已经同时核验。

## 接入示例（纯模型，不调用模型或数据库）

```python
from plugins.corpus.macro_models import Dimensions, MacroObservation, RawAmount, load_record
from plugins.corpus.macro_verification import normalize_jobs

candidate = MacroObservation(
    dimensions=Dimensions(
        country="US", indicator="US.NFP_CHANGE_SA", population="nonfarm_payroll_jobs",
        transform="month_change", adjustment="SA",
    ),
    reference_month=None,  # 不借文档日期补年份。
    role="actual", kind="observed",
    amount=RawAmount(value_raw="162", unit_raw="thousand_jobs"),
)
restored = load_record(candidate.to_json())
assert restored.record_id == candidate.record_id
result = normalize_jobs(candidate)
assert result.value_jobs == 162000
assert result.calculation_permitted is False
```

本示例没有取得官方证据，也没有发行审核记录，只演示模型和尺度转换。
审核调用示例及所有负控见 `tests/test_corpus_macro_models.py`。

## 实施边界

本轮不修改旧 ClaimRecord/EvidenceRun、数据库表、METRICS/RECIPES、默认读取入口或工具注册。
M1 没有把之前宏观留出 0/3 的规范字段自动修好；这里建立的是后续接入所需的受控模型。
后续阶段已迁移至 [统一总计划](plan/claims-market-closed-loop-plan.md)。本模型保留复用，不构成将材料数字自动晋升为数据观测的许可。

2026-09-13 M2 更新：官方适配器实现和离线回归完成，真实归档验收现按用户决定暂跳过，见
[M2 说明](corpus-macro-official-adapter.md)。normalize_jobs 另支持保留原语言的
`in thousands` / `Numbers in thousands`，仅在当前输入获得 indicator + unit_mapping
审核许可时乘 1,000；不放宽未知输入的门禁，不开放计算。
