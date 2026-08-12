-- P1-3: messages 加单调 seq 列。
-- 流式轮里 user + streaming-assistant 在 prepare_persistence 的同一事务插入，
-- created_at（now()，事务级稳定）完全相同；仅 ORDER BY created_at 时同 timestamp 行顺序
-- 非确定（角色可能反转，污染下一轮上下文、偶发严格交替 provider 400）。
-- seq BIGSERIAL 作确定性 tiebreaker：同事务内 user.seq < assistant.seq，顺序恒定。
ALTER TABLE agent_rs.messages ADD COLUMN IF NOT EXISTS seq BIGSERIAL;
