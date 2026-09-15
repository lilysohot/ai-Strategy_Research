# R2 P3-S：全文有界范围提供器验证

日期：2026-09-14。结论：**P3-S结构门通过，R2当前只剩人工原子分母门未完成；P4仍未授权。**

## 执行范围

用户在P3-R结论后指示继续，并要求明确人工参与。本轮新增一个纯计算 scope-provider 模块，其
interface只有 `prepare_scopes(source, binding, limits)` 与确定性重建校验。implementation负责安全
断点、连续覆盖、packet类型、相邻范围身份、硬容量及显式失败；没有新增adapter或生产seam。

只读取四份冻结development来源及六个微范围。没有修改生产parser、P3-R冻结原型、R2生产planner、
runtime/audit/evaluator、service、CLI、gold或budget；模型、judge、PostgreSQL、市场、入库和独立
留出访问均为0。

## 全文结构结果

| 类型 | 结果 |
|---|---:|
| EvidenceRun packet | 14/14 已登记，0 unresolved |
| 来源字符覆盖 | 17,044/17,044 |
| 非空白字符覆盖 | 16,013/16,013 |
| 生成范围 | 65 candidate，0 unresolved |
| prose/turn/heading范围 | 58，全部进入P3-R子句格且0容量/类型失败 |
| table范围 | 7个 `table_row`，送入子句格为0 |
| 范围相邻边 | 51 |
| 子句格节点/边 | 11,230 / 3,327 |

默认每个范围最多320字符。只有在句号、问号、分号、空行、话轮标签或必要时的弱标点处切分；数字
千位逗号不是断点。无法在上限内找到安全断点、范围数量超限、table cell超限、packet不可用或类型
未知时，整个packet返回显式unresolved并保留完整范围，不返回部分成功。本轮四类真实development
均未触发这些失败；相应反例已由测试覆盖。

公司PDF的7个table packet保留为独立 `table_row`，不再被误判为unsupported，也没有伪装成prose。
本轮只证明它们身份和内容完整覆盖；未证明表格claim的行列语义。其余58个范围分别为prose、turn或
heading_context，逐范围进入冻结P3-R模块后全部planned，解决了上一轮整packet造成的6个容量阻塞。

## 固定目标与关系端点

35个固定development目标均落在一个唯一生成范围内；17个正关系、8个负关系的两端均有范围身份。
电话纪要中重复出现的“工艺占大头”使用冻结微范围的来源位置作**评估时**消歧，不参与范围生成。
生成interface仍不接收gold item、关系或排除项。

这只说明“来源范围没有切断目标、关系端点可回取”。P3-R提出的35个最小节点仍全部为
`proposed_not_approved`，系统和agent都没有资格把可定位等同于正确原子分母。

## 门禁

| 门 | 结果 | 依据 |
|---|---|---|
| S0 来源身份与gold隔离 | passed | scope-provider只接收Source、binding、limits |
| S1 packet登记与覆盖 | passed | 14/14 packet，17,044字符完整覆盖，0 unresolved |
| S2 table类型保留 | passed | 7个table_row，0个送入clause lattice |
| S3 prose范围容量 | passed | 58/58范围的子句格根planned |
| S4 固定目标范围覆盖 | passed | 35/35唯一范围 |
| S5 关系端点范围引用 | passed | 正17/17、负8/8 |
| S6 人工原子分母批准 | not_evaluated | 人工签核0/35 |
| S7 生产及旧流程隔离 | passed | P2保护清单与生产模块未改 |

P3-S的机器结构出口已经通过，但S6是不可自动替代的产品语义门。未完成人工复核前，不冻结P4预算，
不运行模型，不把P3-R/P3-S提到生产，也不开始CLI接线。

## 人工参与：具体需要做什么

审阅人只需处理 [35条签核模板](r2-p3s-denominator-review-template.json)，不需要查看或批准65个
机器范围，也不需要判断观点真假。每条对照来源引文和最小节点，填写四个布尔检查项、一个决定及
一段理由。合法决定为：

- `approve`：一条完整研究命题，条件/归属保留，无无关命题，证据坐标充分；
- `needs_split`：仍混有多个独立命题；
- `needs_merge`：缺少必要条件、否定、对象、时间或归属；
- `reject`：不应成为研究item或证据不足。

还需填写审阅人姓名、ISO 8601时间及实际批准总数。完整口径、文件复制方式和校验命令见
[人工复核说明](r2-p3s-human-review-guide.md)。校验器只检查填写完整性和内部一致性，不解释或修改
人工决定。

若35条全部approve，才进入“是否冻结P4有限模型预算”的单独评审；任何split/merge/reject都先在
development零模型修订，不删除失败样本。表格语义不在这35条范围内；未来需要表格claim时必须
另立table item契约。

## 验证与交付

P3-S新增27项测试，与P1/P2/P3/P3-R组合共275项通过。新增源码Ruff通过、目标Pyright为0错误，
import smoke为339/339与388/388，symbol closure为438文件0缺失；P2保护校验仍为2336个旧文件
不变、3个登记私有新增模块哈希一致。全部结果由最终冻结清单绑定。

交付包括 [结构清单](r2-p3s-inventory.json)、[签核模板](r2-p3s-denominator-review-template.json)、
[人工说明](r2-p3s-human-review-guide.md)、[scope-provider](p3s_scope_provider.py)、
[reviewer与校验器](p3s_review.py) 和 [27项测试](test_p3s_scope_provider.py)。冻结清单外部SHA记录在
issue 20 最新执行项。
