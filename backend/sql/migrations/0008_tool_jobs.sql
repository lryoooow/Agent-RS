-- durable 工具任务队列：把"做过什么工具、什么失败了"持久化，并支持重启后恢复孤儿任务。
-- 背景：现状工具在请求内同步执行（runtime → child.py → runner → docker），重启即丢执行记录；
-- 本表做"持久化 + 恢复层"——正常流量仍同步执行实时推 SSE，仅在 child 起止写 job 行；
-- 重启时由后台 worker 捞起 status 仍是 pending/running 的孤儿任务重跑（遥感工具幂等，重跑安全）。
-- 范式对齐 0003_document_ingest_jobs（同为后台任务）：public schema、user_id TEXT 无硬 FK 带默认。
-- 消费闭环：worker 即本表消费者，attempts 到 max_attempts 转 failed 终态，杜绝队列无界增长
--   （直接规避 embedding_retry "有表无消费者" 的历史坑）。
-- 幂等：IF NOT EXISTS，重复启动零副作用。
CREATE TABLE IF NOT EXISTS public.tool_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'running', 'complete', 'failed')),
  tool_name TEXT NOT NULL,
  arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
  imagery_id TEXT,
  user_id TEXT,
  conversation_id TEXT,
  result JSONB,
  error_code TEXT,
  error_message TEXT,
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  heartbeat_at TIMESTAMPTZ,                          -- running 期间周期刷新；判孤儿用
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- worker 捞孤儿的主查询路径：按 status + heartbeat 找超时未完成的任务。
CREATE INDEX IF NOT EXISTS idx_tool_jobs_status_heartbeat
  ON public.tool_jobs (status, heartbeat_at);

-- 按属主 + 时间倒序：未来"我的任务历史"查询路径预留。
CREATE INDEX IF NOT EXISTS idx_tool_jobs_owner_created
  ON public.tool_jobs (user_id, created_at DESC);
