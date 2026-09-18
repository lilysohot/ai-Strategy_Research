"""语料准备 Module（ingestion rebuild）。

统一解析/清洗/切块/发布链路的落点（架构 v1.1 §9 拟定）。本包的守卫
（:mod:`plugins.corpus.preparation.guard`）与契约/存储模块（``contract``/
``repository``）保持**纯标准库**；``readers`` 子包仅允许本地确定性读取库
（PyMuPDF/python-docx，架构 §5.3）。全包不发起任何模型调用；
`tools/import_smoke.py --stage 1` 会遍历导入本包。
"""
