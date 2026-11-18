from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.auth.security import is_secure_auth_secret
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool
from app.mcp.types import MCPServerSpec


def _cipher() -> AESGCM:
    secret = get_settings().auth_secret_key
    if not is_secure_auth_secret(secret):
        raise ValueError("外部服务凭据需要已配置的平台加密密钥")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"agent-rs/mcp-credentials/v1").derive(secret.encode())
    return AESGCM(key)


class RegistryConflictError(RuntimeError):
    pass


class MCPServerRepository:
    async def pool(self):
        pool = await fetch_optional_pool()
        if pool is None:
            raise RuntimeError("MCP 服务持久化需要 PostgreSQL")
        return pool

    async def revisions(self):
        return {row["slug"]: row["updated_at"] for row in await (await self.pool()).fetch(
            "SELECT slug, updated_at FROM agent_rs.mcp_servers")}

    async def list(self) -> list[MCPServerSpec]:
        rows = await (await self.pool()).fetch("SELECT * FROM agent_rs.mcp_servers ORDER BY slug")
        specs = []
        for row in rows:
            encrypted = row["auth_header_encrypted"]
            token = _cipher().decrypt(encrypted[:12], encrypted[12:], row["slug"].encode()).decode() if encrypted else None
            specs.append(MCPServerSpec(slug=row["slug"], name=row["name"], endpoint_url=row["endpoint_url"],
                                       enabled=row["enabled"], timeout_seconds=row["timeout_seconds"], auth_bearer_token=token))
        return specs

    async def save(self, spec: MCPServerSpec, tools: list, status: str, *, create: bool, expected_revision=None):
        secret = spec.auth_bearer_token
        encrypted = None
        if create and secret:
            nonce = os.urandom(12)
            encrypted = nonce + _cipher().encrypt(nonce, secret.get_secret_value().encode(), spec.slug.encode())
        pool = await self.pool()
        if create:
            return await pool.fetchval("""INSERT INTO agent_rs.mcp_servers
                (slug,name,transport,endpoint_url,auth_header_encrypted,enabled,tool_prefix,timeout_seconds,
                 allowed_domains,last_health_status,cached_tools_json) VALUES ($1,$2,'streamable_http',$3,$4,$5,$6,$7,$8,$9,$10::jsonb) ON CONFLICT (slug) DO NOTHING RETURNING updated_at""",
                spec.slug, spec.name, spec.endpoint_url, encrypted, spec.enabled, f"ext_{spec.slug}__",
                spec.timeout_seconds, [urlsplit(spec.endpoint_url).hostname], status, json.dumps(tools))
        else:
            changed = await pool.fetchval("""UPDATE agent_rs.mcp_servers SET enabled=$2,last_health_status=$3,
                cached_tools_json=$4::jsonb,updated_at=clock_timestamp() WHERE slug=$1
                AND ($5::timestamptz IS NULL OR updated_at=$5) RETURNING updated_at""",
                spec.slug, spec.enabled, status, json.dumps(tools), expected_revision)
            if changed is None:
                raise RegistryConflictError("服务记录已在其他进程更改，请刷新后重试")
            return changed

    async def delete(self, slug: str):
        await (await self.pool()).execute("DELETE FROM agent_rs.mcp_servers WHERE slug=$1", slug)
