-- CJK 全文检索修复：PostgreSQL 'simple' 分词器不切中文（无空格→整段一个 token），
-- 导致 content_tsv 全文索引对中文查询命中率≈0，hybrid 检索退化成纯向量单路。
-- 方案（最简、零扩展、零新依赖）：用重叠二字组（bigram）把连续中文切成可被 'simple'
-- 索引的 token——"卫星影像"→"卫星 星影 影像"；写入端（生成列）与查询端用同款切分，对称匹配。
-- 标准 pgvector/pg16 镜像即可，不依赖 zhparser/pg_jieba。
--
-- 幂等：函数 CREATE OR REPLACE；生成列仅当其定义不含新函数时才重建（DO $$ IF $$ 守卫），
-- 重复启动零副作用。生成列重建会从存量 content 自动重算，无需手动回填。

-- 1) 把一段文本里的连续 CJK 字符转成空格分隔的重叠二字组；非 CJK 段（英文/数字/标点）原样保留。
--    例："使用NDVI分析植被覆盖" → "使用 NDVI 分析 析植 植被 被覆 覆盖"（英文 NDVI 交给 'simple' 自身切分）。
--    IMMUTABLE 是进入 GENERATED 列表达式的硬性要求。
CREATE OR REPLACE FUNCTION agent_rs.cjk_bigram(input text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
AS $$
DECLARE
  result text := '';
  ch text;
  run text := '';        -- 当前累积的连续 CJK 串
  i int;
  n int;
BEGIN
  IF input IS NULL OR input = '' THEN
    RETURN '';
  END IF;
  FOR i IN 1 .. char_length(input) LOOP
    ch := substr(input, i, 1);
    IF ch ~ '[一-鿿㐀-䶿豈-﫿぀-ヿ]' THEN
      -- CJK（含统一表意文字 + 扩展A + 兼容 + 日文假名）：累积进 run。
      run := run || ch;
    ELSE
      -- 遇到非 CJK：先把累积的 CJK run 切成 bigram 刷出，再原样追加该字符。
      IF run <> '' THEN
        result := result || ' ' || agent_rs.cjk_run_to_bigrams(run) || ' ';
        run := '';
      END IF;
      result := result || ch;
    END IF;
  END LOOP;
  IF run <> '' THEN
    result := result || ' ' || agent_rs.cjk_run_to_bigrams(run) || ' ';
  END IF;
  RETURN result;
END;
$$;

-- 2) 把一段纯 CJK 串切成重叠二字组；单字串退化为该单字（保证 1 字查询也可命中）。
CREATE OR REPLACE FUNCTION agent_rs.cjk_run_to_bigrams(run text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
AS $$
DECLARE
  n int := char_length(run);
  parts text[] := '{}';
  i int;
BEGIN
  IF n = 0 THEN
    RETURN '';
  ELSIF n = 1 THEN
    RETURN run;
  END IF;
  FOR i IN 1 .. n - 1 LOOP
    parts := array_append(parts, substr(run, i, 2));
  END LOOP;
  RETURN array_to_string(parts, ' ');
END;
$$;

-- 3) 索引端：CJK bigram + 'simple' 配置生成 tsvector。供 content_tsv 生成列使用。
CREATE OR REPLACE FUNCTION agent_rs.to_cjk_tsvector(input text)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT to_tsvector('simple', agent_rs.cjk_bigram(coalesce(input, '')));
$$;

-- 4) 查询端：把查询串按同款 bigram 切分，二字组之间用 & 连接成 tsquery。
--    无有效 token（如纯空白）→ 返回不匹配任何文档的空 tsquery，避免 plainto 在空串上的歧义。
CREATE OR REPLACE FUNCTION agent_rs.to_cjk_tsquery(input text)
RETURNS tsquery
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT plainto_tsquery('simple', agent_rs.cjk_bigram(coalesce(input, '')));
$$;

-- 5) 重建 content_tsv 生成列：旧定义用 to_tsvector('simple', content)，改为 CJK 版。
--    GENERATED 列不能 ALTER 改表达式，只能 DROP 后 ADD；ADD 时从存量 content 自动重算。
--    守卫：仅当当前生成定义里不含 to_cjk_tsvector 时才重建（幂等）。
DO $$
DECLARE
  current_def text;
BEGIN
  SELECT pg_get_expr(d.adbin, d.adrelid)
    INTO current_def
  FROM pg_attribute a
  JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
  WHERE a.attrelid = 'public.document_chunks'::regclass
    AND a.attname = 'content_tsv';

  IF current_def IS NULL OR position('to_cjk_tsvector' IN current_def) = 0 THEN
    -- 索引依赖该列，先删索引再删列。
    DROP INDEX IF EXISTS public.idx_document_chunks_content_tsv;
    ALTER TABLE public.document_chunks DROP COLUMN IF EXISTS content_tsv;
    ALTER TABLE public.document_chunks
      ADD COLUMN content_tsv tsvector
      GENERATED ALWAYS AS (agent_rs.to_cjk_tsvector(content)) STORED;
    CREATE INDEX IF NOT EXISTS idx_document_chunks_content_tsv
      ON public.document_chunks
      USING gin (content_tsv);
  END IF;
END $$;
