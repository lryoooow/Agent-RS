-- 长期记忆结构化。
--
-- 背景：public.memories 从 0000 起就有 memory_type（默认 'fact'）与 importance（默认 0.7）
-- 两列，但 memory_judge 从来只写 content + metadata.tags，两列永远是默认值——
-- 建了但从没真正用过。本迁移把它们变成有约束、可检索的真字段。
--
-- 幂等：全部 IF NOT EXISTS / DO 块保护，可重复执行。

-- 1) memory_type 取值约束。
--    与 app/agent/engine/memory/pg_memory.py:MEMORY_TYPES 保持一致，改一处必须同步改另一处。
--      fact       客观事实（"这个项目用 GF-2 影像"）
--      preference 用户偏好（"回复用中文"）
--      constraint 硬性约束（"结论必须标注数据来源与时间"）
--      project    项目上下文（"当前在做洪涝灾害评估"）
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memories_memory_type_check'
  ) THEN
    -- 先把历史脏值归一到 fact，否则加约束会失败
    UPDATE public.memories
       SET memory_type = 'fact'
     WHERE memory_type IS NULL
        OR memory_type NOT IN ('fact', 'preference', 'constraint', 'project');

    ALTER TABLE public.memories
      ADD CONSTRAINT memories_memory_type_check
      CHECK (memory_type IN ('fact', 'preference', 'constraint', 'project'));
  END IF;
END $$;

-- 2) importance 值域约束 [0, 1]。
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memories_importance_check'
  ) THEN
    UPDATE public.memories
       SET importance = 0.7
     WHERE importance IS NULL OR importance < 0 OR importance > 1;

    ALTER TABLE public.memories
      ADD CONSTRAINT memories_importance_check
      CHECK (importance >= 0 AND importance <= 1);
  END IF;
END $$;

-- 3) 回填历史记忆的类型。
--    历史行只有 metadata.tags 可依据，按 tag 关键词做一次保守推断：
--    只在能明确判断时改写，判断不了的保持 fact，不瞎猜。
UPDATE public.memories
   SET memory_type = 'preference'
 WHERE memory_type = 'fact'
   AND metadata ? 'tags'
   AND EXISTS (
     SELECT 1 FROM jsonb_array_elements_text(metadata -> 'tags') AS t(tag)
      WHERE tag LIKE '%偏好%' OR lower(tag) LIKE '%preference%'
   );

UPDATE public.memories
   SET memory_type = 'constraint'
 WHERE memory_type = 'fact'
   AND metadata ? 'tags'
   AND EXISTS (
     SELECT 1 FROM jsonb_array_elements_text(metadata -> 'tags') AS t(tag)
      WHERE tag LIKE '%约束%' OR tag LIKE '%规定%' OR lower(tag) LIKE '%constraint%'
   );

UPDATE public.memories
   SET memory_type = 'project'
 WHERE memory_type = 'fact'
   AND metadata ? 'tags'
   AND EXISTS (
     SELECT 1 FROM jsonb_array_elements_text(metadata -> 'tags') AS t(tag)
      WHERE tag LIKE '%项目%' OR lower(tag) LIKE '%project%'
   );

-- 4) 检索索引。
--    记忆召回一律先按 user_id 过滤再按向量排序（见 list_relevant_memories），
--    所以复合索引以 user_id 打头；带上 memory_type/importance 便于后续按类型或
--    重要度筛选而不用回表。
CREATE INDEX IF NOT EXISTS memories_user_type_importance_idx
  ON public.memories (user_id, memory_type, importance DESC);
