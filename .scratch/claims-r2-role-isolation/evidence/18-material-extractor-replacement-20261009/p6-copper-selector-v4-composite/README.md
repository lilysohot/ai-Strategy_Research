# Selector v4 deterministic composite replay

P6 以 P4 的 22 份成功响应为基底，并按冻结的 `(packet_id,start,end)` 坐标用 P5 的 35 个终态覆盖；
原响应对象不改写，487 个坐标恰好各出现一次。23 个 response sequence 全部在 replay 模式执行，
模型调用为 0。

结果为 469 items、420 extracted、67 no-supported、0 failed，四个 packet 全部 completed，items task
为 `succeeded / valid / accepted / candidate`。该状态仅表示协议和 controller 质量门闭合，不代表已经
通过冻结语义金标；没有 relations、发布或消费。
