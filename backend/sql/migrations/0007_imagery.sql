-- 影像归属与元数据进 DB：把租户隔离从"读本地 metadata.json 靠约定"升级为"DB owner 查询"。
-- 背景：迁移前 user_owns_imagery 读 storage/imagery/{id}/metadata.json 取 owner_user_id；
-- 影像二进制一旦迁 MinIO，本地 metadata.json 消失 → 鉴权断。故 owner/元数据先进 DB。
-- 范式对齐 public.documents / public.document_ingest_jobs（同为用户私有内容）：
--   public schema、owner_user_id TEXT 无硬 FK 带默认值（与 documents 一致，容错且支持纯算子调试）。
-- 幂等：IF NOT EXISTS，老库重复启动零副作用。
CREATE TABLE IF NOT EXISTS public.imagery (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  imagery_id TEXT NOT NULL UNIQUE,                 -- 现有 12 位 hex，保持兼容
  owner_user_id TEXT NOT NULL DEFAULT '00000000-0000-4000-8000-000000000001',
  workspace_id TEXT,
  filename TEXT,
  sha256 TEXT,
  bounds JSONB,                                    -- EPSG:4326 [west,south,east,north]，镜像 metadata.bounds
  bands INT,
  storage_backend TEXT NOT NULL DEFAULT 'local'    -- 'local' | 'minio'，支持逐景灰度
    CHECK (storage_backend IN ('local', 'minio')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,      -- 完整原 metadata.json 内容，读回与旧 json 同构
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 按 owner 过滤 + 时间倒序：list_imagery / iter_user_imagery_metadata 的主查询路径。
CREATE INDEX IF NOT EXISTS idx_imagery_owner_created
  ON public.imagery (owner_user_id, created_at DESC);
