# R2 P3-R：有限子句格局部原型验证

日期：2026-09-14。结论：**六个固定 development 微范围的结构门通过；全文 scope-provider 与
人工原子分母复核仍未通过，不进入 P4。**

## 为什么执行，以及没有做什么

P3 证明旧 planner 遇到逗号、条件或并列结构时全部降为 unresolved，六个微范围与四类全文均为
0 candidate。用户在该诊断及推荐方案后指示继续，因此本轮只实现 P3-R 的 scratch-only、零模型
bounded clause lattice 原型。没有修改冻结的生产 planner、runtime、audit、evaluator、公共 parser、
旧 scorer、gold、budget、service 或 CLI；没有连接 PostgreSQL、入库、市场接口或独立留出。

本轮采用一个深模块：外部 interface 只有 `prepare_lattice(source, binding, scopes, limits)` 和
确定性重建校验。标点、连接词、说话标签、条件/归属共享 span、备选窗口、身份哈希及容量处理均在
implementation 内。依赖全为进程内纯计算，不新增 adapter 或生产 seam。

## 固定微范围结果

planner 收到的字段只有 scope/sample/source path/source hash/locator；在生成完成后，reviewer 才读取
35个目标及关系用于评估。gold item、正负关系、排除项不会进入 planner interface。

| 微范围 | 字符 | nodes / edges | 唯一最小映射 | 正关系端点 | 负关系端点 |
|---|---:|---:|---:|---:|---:|
| 公司推荐 | 122 | 53 / 19 | 7/7 | 0/0 | 0/0 |
| 行业Q7-Q8 | 239 | 157 / 46 | 14/14 | 11/11 | 3/3 |
| 个人交易TTD | 168 | 21 / 11 | 4/4 | 0/0 | 2/2 |
| 铜箔总结 | 70 | 21 / 11 | 1/1 | 0/0 | 0/0 |
| 铜箔听音 | 21 | 15 / 10 | 1/1 | 0/0 | 0/0 |
| 铜箔良率 | 121 | 93 / 33 | 8/8 | 6/6 | 3/3 |
| 合计 | 741 | 360 / 130 | **35/35** | **17/17** | **8/8** |

35个目标映射到35个不同的唯一最小节点，解决了 P3 的“整个范围只有一个 unresolved 根”问题。
数值中的千位逗号不会被误拆；公司目标价与包含评级的较长表达可落到不同节点；条件和说话归属有
显式 `qualifies` / `attributes` 边。whole span 始终保留，所有 span 可按 source identity 和坐标回取。

这些节点仍全部是 `proposed_not_approved`。35/35表示固定目标能在系统生成的有限格中被唯一定位，
不表示系统已经证明35个节点都是正确、完整的原子分母，也不表示字段语义或模型输出已经通过。

## 容量与全文检查

每根默认最多64个基础段、8段组合窗口、384个节点、768条边；超过上限时只保留绑定的 whole span，
根状态显式为 `unresolved_capacity` 并记录实际所需数量，不截断后伪装成成功。24项原型测试覆盖
段/节点上限、伪造span、错误source binding、计划漂移、条件/归属边、数值逗号及write-once。

四类完整 development 来源仍不能直接放行：14个 packet 根中只有个人交易的1根在默认上限内；
公司7个表格 packet 显式为 unsupported，另1根超限；行业1根和铜箔4根超限。合计1个 planned、
7个 unsupported、6个 unresolved_capacity。该结果确认下一问题在 scope-provider：不能把整份
2.6K—3K字符 packet 直接当作一个原子规划根，也不能把表格无条件冒充 prose。

因此不提高节点上限来掩盖全文问题。下一设计必须先生成有来源坐标的研究范围（章节/段落/话轮/
表格单元及必要上下文），再交给子句格；范围拆分也要有独立容量和失败终态。

## 门禁结论

| 门 | 结果 | 说明 |
|---|---|---|
| R0 gold独立生成 | passed | planner只接收五个来源字段，不接收目标或关系 |
| R1 固定开发item可定位 | passed | 35/35唯一最小节点，35个节点互异 |
| R2 关系端点可引用 | passed | 17正、8负关系的两端均有节点身份 |
| R3 有限容量与无静默截断 | passed | 硬上限及显式unresolved反例通过 |
| R4 条件/归属支持 | passed | `qualifies`、`attributes`均有固定开发证据 |
| R5 人工原子分母批准 | not_evaluated | 35条队列批准数为0 |
| R6 生产/旧流程隔离 | passed | 生产planner及P2保护哈希不变 |

P3-R 是“局部结构可行性成立”，不是 R2 验收完成。P4 必须继续保持未授权；真实 item 终态、字段
忠实度、关系判定和四类非回归均尚未产生新协议证据。

原型24项与P1/P2-A/P2-B/P3组合共248项测试通过；目标Pyright为0错误，Ruff通过，import smoke
为339/339与388/388，symbol closure为438文件0缺失。P2保护校验仍为2336个旧文件不变、3个登记
私有新增模块哈希一致。首次两条import smoke命令误用了不存在的`scripts/`路径，只产生“文件不
存在”并未运行工程逻辑；改用仓库实际`tools/`入口后上述两阶段均通过。

## 下一停止点

本轮输出 [结构清单](r2-p3r-inventory.json)、[35条人工复核队列](r2-p3r-review-queue.json)、
[纯规划模块](p3r_clause_lattice.py)、[离线reviewer](p3r_review.py) 和
[24项测试](test_p3r_clause_lattice.py)。冻结清单外部SHA记录在 issue 20 最新执行项。

下一步不能直接调用模型。需要两项前置决策：

1. 人工逐条批准或拒绝35个唯一最小节点作为固定 development 原子分母；agent proposal不能代签。
2. 是否授权独立的 P3-S scope-provider 零模型原型，解决全文大根与table packet；它仍只能在scratch，
   并需证明不改变其他研报既有 parser/入口。

只有人工分母通过、P3-S逐类范围门通过并再次完成旧流程隔离，才有资格另行评审 P4 有限模型预算。
