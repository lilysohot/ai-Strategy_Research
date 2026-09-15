# R2 语料证据流水线 · 流程总图

| 项 | 内容 |
|---|---|
| 版本 / 状态 | v1.0 · 2026-09-14（R2 执行态） |
| 用途 | 展示「语料证据链 → R2 阶段门禁 → 人工复核 → 预算冻结」的完整流程 |
| 配套 | [指导解析](r2-corpus-evidence-pipeline-guide.md) |
| 事实真源 | [spec.md](../../.scratch/corpus-evidence-pipeline/spec.md)、[business-process.md](../business-process.md) |

## 1. 完整证据链（数据 → 可推导证据）

```mermaid
flowchart LR
    A["源文件<br/>研报 / 纪要 / 评论 / 复盘"] --> B["保真解析与证据包<br/>原文 + 定位 + 坐标"]
    B --> C["规范化与质量门禁<br/>单位 / 期间 / 证据校验"]
    C --> D["版本存储与抽取编排<br/>影子证据 · 幂等重跑"]
    D --> E["可计算投影与推导<br/>公式绑定事实 ID / 期间 / 单位"]
    E --> F["版本化保存 / 取回 / 复算"]
```

## 2. R2 阶段门禁链（P0 → P4）

```mermaid
flowchart TD
    subgraph S1["机器结构门"]
        P0["P0 基线<br/>冻结最小契约与联合金标"] --> P1["P1 接口契约"]
        P1 --> P2["P2 技术门<br/>PG 只读核查 · 事故保留"]
        P2 --> P3["P3 固定开发回放<br/>planner 诊断"]
        P3 --> P3R["P3-R 有限子句格<br/>11,230 节点 / 3,327 边<br/>35 个最小节点 proposed"]
        P3R --> P3S["P3-S 全文范围提供器<br/>65 范围 · 58 prose · 7 table_row<br/>覆盖 17,044 字符"]
    end
    P3S --> S6{"S6 人工原子分母批准<br/>35 条签核"}
    S6 -- "split / merge / reject" --> DEV0["development 零模型修订"]
    DEV0 --> P3H
    S6 -- "全部 approve" --> P3H["P3-H 人工裁决应用<br/>31 approve / 2 split / 1 merge / 1 reject<br/>amendment overlay · base 不变"]
    P3H --> H4{"H4 替代 item 人工批准<br/>5 条"}
    H4 -- "未批准" --> DEV1["development 零模型修订"]
    DEV1 --> P3I
    H4 -- "5/5 approve" --> P3I["P3-I 字段契约桥接<br/>8 speaker · 8 value · 49 unknown 约束<br/>零模型调用"]
    P3I --> I6{"I6 人工桥接批准<br/>全局规则 + speaker + value/unit"}
    I6 -- "needs_revision / reject" --> DEV1
    I6 -- "全部批准" --> P4["P4 预算批准<br/>35 item · 5 调用 · 0 重试<br/>前置：scratch runtime / scorer 反例"]
```

## 3. P3-S 人工复核：四项检查与裁决流

```mermaid
flowchart TD
    R["审阅人收到 35 条签核模板"] --> C1{"检查1<br/>一条完整研究命题?"}
    C1 -- "否" --> SPLIT["needs_split<br/>仍混有多个独立命题"]
    C1 -- "是" --> C2{"检查2<br/>必要条件 / 归属保留?"}
    C2 -- "否" --> MERGE["needs_merge<br/>缺条件 / 否定 / 对象 / 时间 / 归属"]
    C2 -- "是" --> C3{"检查3<br/>无无关命题混入?"}
    C3 -- "否" --> SPLIT
    C3 -- "是" --> C4{"检查4<br/>引文与定位充分?"}
    C4 -- "否" --> REJECT["reject<br/>不应成为研究 item / 证据不足"]
    C4 -- "是" --> APPROVE["approve"]
```

## 4. P3-I 字段契约桥接：35 条投影规则

```mermaid
flowchart LR
    A["35 条已批准原子分母"] --> B["speaker_ref<br/>scope_id + role + identity_status<br/>8 个去重 registry · 可逆"]
    A --> C["value<br/>27 unknown · 5 源字面 · 3 白名单转换"]
    A --> D["unit<br/>仅源引文明确 元 / $ · 否则 unknown"]
    A --> E["unknown_fields<br/>49 个约束 · 无丢失无冲突"]
    B --> F["仅供 evaluator 使用<br/>禁止进入模型 prompt"]
    C --> F
    D --> F
    E --> F
```
