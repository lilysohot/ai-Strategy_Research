-- 语料库初始化（第二步）：建表 + 索引 + 字段注释
-- 仅在数据库**首次初始化**时执行（docker-entrypoint-initdb.d，按文件名顺序运行在 00-extensions.sql 之后）
--
-- ⚠️ 同步要求：本文件的表结构与 plugins/corpus/service.py 的 SCHEMA_SQL / _COLUMN_COMMENTS
--    必须保持一致。改动 schema 时**两处都要改**。
--    为什么两份：本文件负责「容器首次启动即有表可用」（无需先跑一次服务层 init_db）；
--    service.py 那份负责「已存在库上幂等补齐」（CREATE IF NOT EXISTS + COMMENT ON 可重复执行）。
--
-- ⚠️ 生效条件：initdb 脚本只在**数据卷为空**时执行一次。已有数据的容器不会重跑，
--    此时由服务层 CorpusService.init_db() 幂等补齐。

CREATE TABLE IF NOT EXISTS documents (
    doc_id       text PRIMARY KEY,
    title        text        NOT NULL,
    source_path  text        NOT NULL,
    content_hash text        NOT NULL UNIQUE,   -- 幂等去重键
    mime         text        NOT NULL,
    status       text        NOT NULL,          -- ok / needs_ocr / empty
    char_count   integer     NOT NULL DEFAULT 0,
    block_count  integer     NOT NULL DEFAULT 0,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    published    date,                          -- 时效；从 doc_id 日期前缀派生
    -- 标题 FTS 向量：GENERATED 列，入库自动维护，无需手动建索引
    title_tsv    tsvector GENERATED ALWAYS AS (to_tsvector('zhcfg', title)) STORED
);

CREATE TABLE IF NOT EXISTS blocks (
    doc_id  text    NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq     integer NOT NULL,
    locator text    NOT NULL,   -- PDF=页码；DOCX/MD=标题或段落
    text    text    NOT NULL,   -- 逐字原文（硬闸①取证来源）
    -- 正文 FTS 向量：GENERATED 列
    tsv     tsvector GENERATED ALWAYS AS (to_tsvector('zhcfg', text)) STORED,
    PRIMARY KEY (doc_id, seq)
);

-- 取证：(doc_id, locator)。P0 识别出的缺失索引，趁迁移补上
CREATE INDEX IF NOT EXISTS idx_blocks_locator      ON blocks (doc_id, locator);
-- 全文检索（必要）：GIN 索引，否则 @@ 走全表扫描
CREATE INDEX IF NOT EXISTS idx_blocks_tsv          ON blocks USING gin (tsv);
-- 时效排序与 Recency 偏置
CREATE INDEX IF NOT EXISTS idx_documents_published ON documents (published DESC);

-- ── 字段注释（让库自带说明，无需翻代码）──────────────────
COMMENT ON TABLE documents IS '语料文档元数据：一份研报/文章一条记录';
COMMENT ON COLUMN documents.doc_id IS '文档唯一标识：<日期>_<内容哈希前8位>；短且无中文，供模型抄进 evidence.source_ref';
COMMENT ON COLUMN documents.title IS '去噪后的标题；同时生成 title_tsv 进 FTS 标题权重（A 权重）';
COMMENT ON COLUMN documents.source_path IS '原始文件相对路径，可回溯到磁盘';
COMMENT ON COLUMN documents.content_hash IS '文件字节 SHA-256 前 16 位；幂等去重键（UNIQUE）';
COMMENT ON COLUMN documents.mime IS 'MIME 类型：application/pdf / text/markdown / docx...';
COMMENT ON COLUMN documents.status IS '入库状态：ok / needs_ocr / empty';
COMMENT ON COLUMN documents.char_count IS '全文字符数（含空白）';
COMMENT ON COLUMN documents.block_count IS '切块数';
COMMENT ON COLUMN documents.ingested_at IS '入库时间（默认 now()）';
COMMENT ON COLUMN documents.published IS '发布/收录日期，从 doc_id 日期前缀派生';
COMMENT ON COLUMN documents.title_tsv IS '标题 FTS 向量（zhcfg 中文分词），GENERATED 列自动维护';

COMMENT ON TABLE blocks IS '可定位的原文块：一份文档切成多条';
COMMENT ON COLUMN blocks.doc_id IS '外键→documents(doc_id)，级联删除';
COMMENT ON COLUMN blocks.seq IS '块序号，同文档内从 1 递增，用于排序';
COMMENT ON COLUMN blocks.locator IS '定位符：PDF=页码；DOCX/MD=标题/段落。取证句柄之一';
COMMENT ON COLUMN blocks.text IS '块内逐字原文；硬闸①逐字比对的来源';
COMMENT ON COLUMN blocks.tsv IS '正文 FTS 向量（zhcfg），GENERATED 列自动维护';
