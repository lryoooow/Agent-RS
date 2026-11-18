"""Authenticated administration of remote MCP servers."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.api.deps import require_admin
from app.core.settings import get_settings
from app.db.repositories.mcp_servers import RegistryConflictError
from app.mcp.hub import get_mcp_hub
from app.mcp.types import MCPCallError, MCPServerSpec

router = APIRouter(prefix="/admin/mcp/servers", tags=["mcp"], dependencies=[Depends(require_admin)])


class ExternalServer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    endpoint_url: str = Field(max_length=2048)
    auth_bearer_token: SecretStr | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=600, allow_inf_nan=False)
    transport: str = Field(default="streamable_http", pattern="^streamable_http$")
    enabled: bool = True

    def spec(self):
        values = self.model_dump(exclude_none=True)
        values.setdefault("timeout_seconds", get_settings().mcp_external_default_timeout)
        return MCPServerSpec.model_validate(values)


class EnableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


def view(server):
    return {"slug":server.spec.slug, "name":server.spec.name, "transport":server.spec.transport,
            "enabled":server.spec.enabled, "health":server.status, "static":server.static,
            "tools":list(server.tools), "resources":[v.get("uri") for v in server.resources],
            "prompts":[v.get("name") for v in server.prompts]}


async def perform(operation):
    try:
        return await operation
    except KeyError:
        raise HTTPException(404, "没有找到指定 MCP 服务") from None
    except ValueError:
        raise HTTPException(422, "MCP 服务地址、名称、凭据配置或工具参数定义无效") from None
    except (MCPCallError, TimeoutError):
        raise HTTPException(502, "远程 MCP 服务没有返回有效响应") from None
    except RegistryConflictError:
        raise HTTPException(409, "服务记录已更改，请刷新后重试") from None
    except RuntimeError:
        raise HTTPException(503, "MCP 配置存储不可用") from None


@router.get("")
async def servers():
    return [view(server) for server in get_mcp_hub().servers.values()]


@router.post("/probe")
async def probe(body: ExternalServer):
    if not get_settings().mcp_hotplug_enabled:
        raise HTTPException(409, "MCP 热插拔已关闭")
    spec = body.spec().model_copy(update={"enabled": True})
    return view(await perform(get_mcp_hub().probe(spec)))


@router.post("", status_code=201)
async def register(body: ExternalServer):
    return view(await perform(get_mcp_hub().register_external_server(body.spec())))


@router.patch("/{slug}")
async def enable(slug: str, body: EnableRequest):
    return view(await perform(get_mcp_hub().set_enabled(slug, body.enabled)))


@router.post("/{slug}/refresh")
async def refresh(slug: str):
    hub = get_mcp_hub()
    current = hub.servers.get(slug)
    if current is None:
        raise HTTPException(404, "没有找到指定 MCP 服务")
    return view(await perform(hub.set_enabled(slug, current.spec.enabled)))


@router.delete("/{slug}", status_code=204)
async def remove(slug: str):
    await perform(get_mcp_hub().unregister_external_server(slug))
