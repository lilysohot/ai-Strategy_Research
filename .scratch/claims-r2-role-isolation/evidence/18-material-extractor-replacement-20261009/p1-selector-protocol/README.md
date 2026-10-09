# Issue 18 P1 · items selector protocol 零调用冻结

本冻结包完成 `material_items` extractor 的第一阶段替换，不发起真实模型调用，不访问生产数据库，
不发布候选。

新协议 `material-atomic-selector-jsonl-v1` 不再要求模型复制 opaque slot ID、item ID、speaker ID 或
逐字引文。模型只返回批内 `obligation_index`、受约束语义字段和固定 `evidence_selector="slot"`；
控制器从冻结 source span 生成业务 item ID、逐字 evidence quote 和每槽终态。缺失、重复、非法响应
均被控制器写为显式 `failed`，不会再表现为 `terminal_record_missing`。

`24` 只是新 selector 协议第一次实跑前的安全上限。计划同时冻结 64 item 输出容量和 8192 估算
token 容量，批次由三项约束共同决定。旧 `material-atomic-jsonl-v5` 仍可读取和显式规划，历史计划
身份没有被改写。

零调用 copper 反事实覆盖全部 487 槽，形成 23 个 items 批次，最大批次 24 槽；该结果只冻结下一次
调用上限，不授权调用。HTML span/style、speaker 标签和重复文本测试均证明 evidence 由原始坐标切片，
而不是采用模型改写文本。

验证与字节哈希见 [manifest.json](manifest.json)。下一子阶段是 relations selector 协议；在它和旧响应
差分门完成前，不生成新的 live plan。
