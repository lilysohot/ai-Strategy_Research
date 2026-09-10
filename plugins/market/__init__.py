"""market 模块：给 Agent 提供同花顺（fuyao）市场数据的取数工具与治理。

分层（§5.0，依赖单向）：
    ports（协议/数据类，零依赖） → transport（HTTP 治理） → adapters（业务语义）
    → service（收口） → tools（Agent 可见）

本模块**不落库、不跑批、不建表**；留痕只写 run 目录（可选）。
"""
