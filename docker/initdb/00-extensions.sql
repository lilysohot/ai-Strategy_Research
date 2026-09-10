-- 语料库初始化：扩展 + 中文检索配置
-- 仅在数据库首次初始化时执行（docker-entrypoint-initdb.d）

-- pgvector：向量检索留位（当前不建列，启用判据见 pg-migration.md §7）
CREATE EXTENSION IF NOT EXISTS vector;

-- pg_trgm：数字 / 子串兜底（zhparser 切不动数字时的补充）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- zhparser：中文分词（PG 内置 FTS 无中文分词器，必须装）
CREATE EXTENSION IF NOT EXISTS zhparser;

-- 中文全文检索配置：所有词性都映射到 simple 词典（中文不做词干还原）
-- 注意：必须包含 'm'（数词），否则 "47.3亿" 这类数字会被丢弃，数字检索失效
ALTER TEXT SEARCH CONFIGURATION IF NOT EXISTS zhcfg DROP MAPPING IF EXISTS FOR a,b,c,e,f,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z;
CREATE TEXT SEARCH CONFIGURATION IF NOT EXISTS zhcfg (PARSER = zhparser);
ALTER TEXT SEARCH CONFIGURATION zhcfg
  ADD MAPPING FOR a,b,c,e,f,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z WITH simple;
