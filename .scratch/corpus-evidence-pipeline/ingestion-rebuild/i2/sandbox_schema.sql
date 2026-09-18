-- I2-1 隔离库 DDL（i0c-r1 冻结布局：corpus schema 九表；I2-3 修订 r3：补读侧筛选索引）
-- 依据：.scratch/corpus-evidence-pipeline/ingestion-rebuild/design-review.json（签认版，sha=3c346c61…）
--       §i0c_1_candidates C1—C7/C14/C15 ddl_mapping + §store_persistence_mapping
--       + C13（FTS：zhcfg 分词基线 / search_tsv GIN / 身份·领域·发布日期关联筛选索引）
-- 目标：corpus-db 容器 i2_sandbox_corpus（仅隔离演练；生产 schema 创建留 I4 窗口）
-- 纪律：本文件由 i2s1_apply.py 在 fail-closed 目标校验后执行（单事务）；重演须先跑
--       i2s1_teardown.py（精确范围：仅 corpus schema，DROP 后核验零残留）。

-- 扩展与中文检索配置（每数据库对象；initdb 脚本只作用于容器默认库，新库须自建）
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS zhparser;

-- zhcfg：全词性映射 simple（必须含 'm' 数词，否则 "47.3亿" 类数字被丢弃——initdb 实测教训）；
-- TEXT SEARCH 家族无 IF NOT EXISTS，由 apply 脚本条件创建后执行本文件。
-- CREATE TEXT SEARCH CONFIGURATION zhcfg (PARSER = zhparser);
-- ALTER TEXT SEARCH CONFIGURATION zhcfg
--   ADD MAPPING FOR a,b,c,e,f,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z WITH simple;

CREATE SCHEMA corpus;

-- C1 来源（内容寻址身份；G5：current_decision_id 为 latest_admission 显式指针列）
CREATE TABLE corpus.corpus_sources (
    source_id           char(64) PRIMARY KEY,
    format              text     NOT NULL,
    mime_type           text     NOT NULL,
    size_bytes          bigint   NOT NULL CHECK (size_bytes >= 0),
    archive_path        text     NOT NULL,
    original_names      text[]   NOT NULL DEFAULT '{}',
    current_decision_id text
);
COMMENT ON TABLE corpus.corpus_sources IS '原始来源：source_id=完整 SHA-256（仅由原始字节决定）；同源不同文件名保留别名';

-- C14 人工审核记录（追加式；取代链显式自引用；依据不可空）
-- 注意：source_id 不设 FK——审核终态（I0A-2）先于新链接收存在（§5.2 绑定按哈希值），
--       FK 会令先审后收的真实流程不可行（I2-2 测试揭出，i0c-r2 修正）。
CREATE TABLE corpus.corpus_review_decisions (
    decision_id    text        PRIMARY KEY,
    source_id      char(64)    NOT NULL,
    reviewer       text        NOT NULL,
    reviewed_at    timestamptz NOT NULL,
    decision       text        NOT NULL CHECK (decision IN ('admitted', 'excluded', 'excluded_from_active')),
    rationale      text        NOT NULL,
    scope_ref      text,
    supersedes     text        REFERENCES corpus.corpus_review_decisions (decision_id),
    locators       text[]      NOT NULL DEFAULT '{}',
    material_type  text,
    research_domain text
);
CREATE INDEX idx_review_decisions_source ON corpus.corpus_review_decisions (source_id);
COMMENT ON TABLE corpus.corpus_review_decisions IS '人工审核：§5.2 判定次序第 1 步对象；多 tip/断链/成环=conflicting_review，不凭时间猜取代';

-- C2 准入（追加不可变；scope_ref 为部分章节批准的唯一合法表达）
CREATE TABLE corpus.corpus_admissions (
    decision_id       text      PRIMARY KEY,
    source_id         char(64)  NOT NULL REFERENCES corpus.corpus_sources (source_id),
    material_type     text,
    research_domain   text,
    decision          text      NOT NULL CHECK (decision IN ('in_scope', 'excluded_by_policy', 'review_required')),
    policy_rev        text      NOT NULL DEFAULT '',
    reason_codes      text[]    NOT NULL DEFAULT '{}',
    scope_ref         text,
    evidence_refs     text[]    NOT NULL DEFAULT '{}',
    review_ref        text,
    rule_rev          text      NOT NULL DEFAULT '',
    metadata_snapshot jsonb     NOT NULL DEFAULT '{}'::jsonb
);
COMMENT ON COLUMN corpus.corpus_admissions.metadata_snapshot IS '§4.3：report_publication（value/precision/status/evidence_refs/origin/review_ref）为研报发布日期唯一落点';

-- C3 构建（版本身份；发布后内容不可修改）
CREATE TABLE corpus.corpus_builds (
    build_id           char(64) PRIMARY KEY,
    source_id          char(64) NOT NULL REFERENCES corpus.corpus_sources (source_id),
    decision_id        text     NOT NULL REFERENCES corpus.corpus_admissions (decision_id),
    parse_rev          text     NOT NULL,
    clean_rev          text     NOT NULL,
    chunk_rev          text     NOT NULL,
    index_rev          text     NOT NULL,
    scope_ref          text,
    config_fingerprint text,
    artifact_manifest  text[]   NOT NULL DEFAULT '{}',
    quality_report     jsonb
);

-- C4 原文结构单元（引用唯一权威：raw_text+坐标+content_hash）
CREATE TABLE corpus.corpus_units (
    build_id     char(64) NOT NULL REFERENCES corpus.corpus_builds (build_id),
    unit_id      text     NOT NULL,
    parent_id    text,
    ordinal      integer  CHECK (ordinal IS NULL OR ordinal >= 0),
    kind         text     NOT NULL,
    raw_text     text     NOT NULL,
    content_hash char(64) NOT NULL,
    location     jsonb    NOT NULL DEFAULT '{}'::jsonb,
    clean_view   text,
    mapping      jsonb    NOT NULL DEFAULT '[]'::jsonb,
    status       text     NOT NULL DEFAULT 'kept',
    reasons      text[]   NOT NULL DEFAULT '{}',
    PRIMARY KEY (build_id, unit_id)
);
COMMENT ON TABLE corpus.corpus_units IS '§4.2 权威映射：raw_text+location(page/element/char_span[basis Unicode code point]/bbox/cells)+content_hash；clean_view/mapping/status 为投影台账';

-- C5 检索投影（可重建；unit_refs 全量闭合、context_refs 为关联角色子集——数组元素归属由 Interface 层校验）
CREATE TABLE corpus.corpus_chunks (
    build_id      char(64) NOT NULL REFERENCES corpus.corpus_builds (build_id),
    chunk_id      text     NOT NULL,
    kind          text     NOT NULL,
    unit_refs     text[]   NOT NULL CHECK (array_length(unit_refs, 1) >= 1),
    context_refs  text[]   NOT NULL DEFAULT '{}',
    search_text   text     NOT NULL,
    title_text    text,
    section_path  text[]   NOT NULL DEFAULT '{}',
    source_ranges jsonb    NOT NULL DEFAULT '[]'::jsonb,
    search_tsv    tsvector GENERATED ALWAYS AS (to_tsvector('zhcfg', search_text)) STORED,
    PRIMARY KEY (build_id, chunk_id)
);
CREATE INDEX idx_chunks_tsv      ON corpus.corpus_chunks USING gin (search_tsv);
CREATE INDEX idx_chunks_unitrefs ON corpus.corpus_chunks USING gin (unit_refs);

-- I2-3 读侧筛选索引（C13 ddl_mapping 定稿：身份/领域/发布日期）。检索纪律
-- （search_pg.py）：先按 corpus_publications.active_build_id 筛活动范围，
-- 再 ts_rank 排名；退役/未发布 build 的 chunk 永不入候选。
-- 身份：来源→构建历史（同源多版本构建定位与审计）。
CREATE INDEX idx_builds_source ON corpus.corpus_builds (source_id);
-- 身份：决定→构建（领域/发布日期过滤经由 admission 定位 build 集）。
CREATE INDEX idx_builds_decision ON corpus.corpus_builds (decision_id);
-- 领域筛选（仅 in-scope 准入携带领域；partial 排除 NULL 行）。
CREATE INDEX idx_admissions_domain ON corpus.corpus_admissions (research_domain)
    WHERE research_domain IS NOT NULL;
-- 发布日期筛选（§4.3 唯一落点 metadata_snapshot.report_publication.value；
-- ISO 文本序=时序；仅研报携带该键，partial 排除 NULL 行）。
CREATE INDEX idx_admissions_report_pub ON corpus.corpus_admissions
    ((metadata_snapshot->'report_publication'->>'value'))
    WHERE metadata_snapshot->'report_publication'->>'value' IS NOT NULL;

-- C6 活动版本（source 唯一；activated_at 由数据库在指针翻转事务内生成——publish_idempotency_v2）
CREATE TABLE corpus.corpus_publications (
    source_id           char(64) PRIMARY KEY REFERENCES corpus.corpus_sources (source_id),
    current_decision_id text     NOT NULL REFERENCES corpus.corpus_admissions (decision_id),
    active_build_id     char(64) REFERENCES corpus.corpus_builds (build_id),
    generation          integer  NOT NULL CHECK (generation >= 1),
    activated_at        timestamptz NOT NULL
);
-- 身份：活动范围反向定位（GIN 候选回接活动集 / 按 build 查活动 source）；
-- 置于 C6 表定义之后（检索纪律第一步即按此列筛活动范围）。
CREATE INDEX idx_publications_active_build ON corpus.corpus_publications (active_build_id);

-- C7 job（每 attempt 一行；单活租约=partial unique；attempt 历史按行追加——契约 §8.1）
CREATE TABLE corpus.corpus_jobs (
    build_id     char(64) NOT NULL REFERENCES corpus.corpus_builds (build_id),
    stage        text     NOT NULL,
    attempt      integer  NOT NULL CHECK (attempt >= 1),
    state        text     NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    owner_id     text,
    fence_token  text,
    lease_until  timestamptz,
    heartbeat_at timestamptz,
    error        text,
    checkpoint   jsonb,
    PRIMARY KEY (build_id, stage, attempt)
);
CREATE UNIQUE INDEX uq_jobs_single_running ON corpus.corpus_jobs (build_id, stage) WHERE state = 'running';
CREATE INDEX idx_jobs_current ON corpus.corpus_jobs (build_id, stage, attempt DESC);
COMMENT ON TABLE corpus.corpus_jobs IS '§8.1：fencing 写入=条件 UPDATE(attempt+state+lease_until+fence_token) 零行即 lease_lost；PUBLISHED 阶段 succeeded 可重新 acquire（消耗 attempt）支持撤销后重发布';

-- C15 来源级（pre-build）解析检查点：(source_id, stage) 键；last-write-wins（与 job 级相反）
CREATE TABLE corpus.corpus_source_checkpoints (
    source_id   char(64)    NOT NULL,
    stage       text        NOT NULL,
    checkpoint  jsonb       NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, stage)
);
COMMENT ON TABLE corpus.corpus_source_checkpoints IS '解析先于准入/建 build，故按来源键控（非 build_id）；payload 含 schema_rev=parse-checkpoint-2 + payload_hash，引擎校验后复用或重算';

-- G5：来源当前决定指针（latest_admission 落点；put_admission 同事务更新；放行可空）
ALTER TABLE corpus.corpus_sources
    ADD CONSTRAINT fk_sources_current_decision
    FOREIGN KEY (current_decision_id) REFERENCES corpus.corpus_admissions (decision_id);
