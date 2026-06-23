-- 邀请码准入：定向邀请 SaaS 内测的注册门控。仅存邀请码的 HMAC（code_hash），不存明文，
-- 明文仅在管理员创建时返回一次。背景：注册此前完全开放，本表把"谁能注册"收敛为管理员签发。
-- 范式对齐 agent_rs schema 的 users/sessions：UUID 主键、created_by_user_id 引用 users。
-- 单次/限时由 max_uses + expires_at 承载；撤销用 revoked 软删（保留审计，不物理删行）。
-- 消费的并发安全由仓储层 UPDATE…WHERE used_count<max_uses RETURNING 的原子性保证（见 _pg/invite.py）。
-- 幂等：IF NOT EXISTS，重复启动零副作用。
CREATE TABLE IF NOT EXISTS agent_rs.invites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code_hash TEXT NOT NULL UNIQUE,                     -- HMAC-SHA256(规范化邀请码, auth_secret_key)
  label TEXT NOT NULL DEFAULT '',                     -- 管理员备注（发给谁/用途），便于追踪
  created_by_user_id UUID NOT NULL REFERENCES agent_rs.users(id),
  expires_at TIMESTAMPTZ,                             -- NULL = 永不过期
  max_uses INT NOT NULL DEFAULT 1,                    -- 1 = 单次邀请
  used_count INT NOT NULL DEFAULT 0,
  used_by_user_id UUID REFERENCES agent_rs.users(id), -- 最近一次消费者（单次码即唯一消费者）
  used_at TIMESTAMPTZ,
  revoked BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 注册时按 code_hash 查码（消费主查询路径）。UNIQUE 约束已建索引，这里显式保留以示意图。
CREATE INDEX IF NOT EXISTS idx_invites_code_hash
  ON agent_rs.invites (code_hash);

-- 管理界面"邀请列表"按创建时间倒序。
CREATE INDEX IF NOT EXISTS idx_invites_created
  ON agent_rs.invites (created_at DESC);
