"""投研资料库与策略卡领域层（P0a 内核 + P0b 数据面）。

这里只放**确定性**的东西：策略卡 schema 常量、引用纪律提示词、以及（P0b 起）
ingest / FTS5 检索。任何模块都**不得**依赖 LLM。

分层约束：``tools/import_smoke.py --stage 1`` 会遍历导入 ``plugins`` 下的每一个
模块。因此本包在 P0a 必须保持**纯标准库**——``pymupdf`` / ``jieba`` 只有 P0b 的
ingest 管道需要，届时应放到延迟导入或单独的 extra 里，否则 stage 1 会红。
"""
