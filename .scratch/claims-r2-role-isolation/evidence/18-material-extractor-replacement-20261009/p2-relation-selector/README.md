# P2 relation selector zero-call freeze

本目录冻结 Issue 18 的 relations extractor 替换。没有执行模型、生产数据库、发布、query、delivery
或 context use。

新协议 `material-relations-selector-jsonl-v1` 保留确定性 candidate-pair 规则，但把 pair ID、端点、关系
类型、relation ID 和证据坐标全部收回 controller。模型每个候选只返回批内整数 `relation_index`、
`present/absent` 与固定 `pair_window` selector。缺失、重复、非法终态使 packet 显式 partial。

对既有 copper items payload 做只读反事实：391 个合格端点仍生成原有 180 个候选对，controller 对
180/180 均生成与冻结 packet `[start,end)` 完全相等的逐字 window。旧 run 中 5 个带伪 speaker prefix
的自由引文失败因此被结构性移除；没有改写旧 response，也没有把旧语义决定算作新协议通过。

验证结果与文件指纹见 `manifest.json`。下一门是单次 copper-only selector live plan；未达到
487/487 槽终态完整、0 partial 和 strict complete-parent gate 时，不开展 items/relations 人工裁定，
也不发布或消费。
