CREATE TABLE IF NOT EXISTS agent_rs.mcp_servers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE,
    name text NOT NULL,
    transport text NOT NULL CHECK (transport = 'streamable_http'),
    endpoint_url text NOT NULL,
    auth_header_encrypted bytea,
    enabled boolean NOT NULL DEFAULT true,
    tool_prefix text NOT NULL UNIQUE,
    timeout_seconds double precision NOT NULL CHECK (timeout_seconds > 0 AND timeout_seconds <= 600),
    allowed_domains text[] NOT NULL DEFAULT '{}',
    last_health_status text NOT NULL DEFAULT 'unavailable',
    cached_tools_json jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
