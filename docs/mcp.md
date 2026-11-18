# Docker 算子与 MCP 接入指南

## 按次运行栅格算子

在项目根目录构建镜像，后端运行账号需要能访问 Docker。

```bash
docker build -t rs-tools-mcp:0.1.0 docker/rs_tools
```

后端配置使用 `RS_TOOLS_MCP_USE_DOCKER=true`、`RS_TOOLS_TRANSPORT=stdio_docker`。平台为每次调用启动命名容器，经标准输入输出进行 MCP 握手和 `tools/call`，收到成功结果后发布产物。超时或取消会回收本次容器。需要检查镜像中实际注册的工具时，可在项目根目录运行以下 Bash 命令。

```bash
docker run --rm -i --network none rs-tools-mcp:0.1.0 <<'MCP'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"operator-check","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
MCP
```

可用一幅带有红光和近红外波段的 GeoTIFF 做业务验收。在工作台选中影像，说明红光、近红外的波段号，请智能体“计算这幅影像的 NDVI”。确认工具执行成功后，到图层查看预览并下载 GeoTIFF。自然语言中的波段号应以影像的元数据为准。

## 常驻 Docker MCP 服务

示例 Compose 提供栅格服务。后端和工作容器需要共享同一个宿主机任务目录。Linux 上目录和每次调用创建的私有子目录需要由相同的 UID/GID 读写。以下命令在运行后端的主机执行。令牌应由私有配置或密钥管理器同时提供给后端与容器。

```bash
export RS_TOOLS_HTTP_WORKSPACE="$PWD/.rs-mcp-jobs"
mkdir -p -m 700 "$RS_TOOLS_HTTP_WORKSPACE"
export RS_TOOLS_WORKER_UID="$(id -u)" RS_TOOLS_WORKER_GID="$(id -g)"
# 将私有密钥管理器提供的值导出为 RS_TOOLS_HTTP_TOKEN 后启动
docker compose -f docker/operator_mcp/compose.yaml up -d --build raster
```

在后端设置 `RS_TOOLS_TRANSPORT=streamable_http`、`RS_TOOLS_HTTP_URL=http://127.0.0.1:18130/mcp`、相同的 `RS_TOOLS_HTTP_TOKEN` 和绝对路径 `RS_TOOLS_HTTP_WORKSPACE`。宿主机回环地址适用于同机启动的后端。后端也在容器中时，将工作目录绑定挂载到后端，按实际容器网络填写可达的服务地址。每个请求有独立输入、输出目录，结果仍经平台发布。需要随时回退时，可在启动后端前把 `RS_TOOLS_TRANSPORT_FILE` 指向运维维护的文件。在同一目录原子替换该文件，内容写 `stdio_docker` 或 `streamable_http`，下一个算子调用即采用指定方式，在途任务继续使用原传输。仅使用环境变量的部署需重新载入后端配置。

启用常驻 OCR 时，先执行 `docker build -t rs-doc-mcp:0.1.0 docker/rs_doc`，再运行 `docker compose -f docker/operator_mcp/compose.yaml --profile ocr up -d --build`。同机后端的 `RS_DOC_HTTP_URL` 可填 `http://127.0.0.1:18132/mcp`。

检测与 OCR 基于各自的算子镜像加载同一 FastMCP 服务入口，分别配置 `RS_DETECT_HTTP_URL`、`RS_DOC_HTTP_URL`。只启用栅格热池时，未配置常驻端点的检测与 OCR 仍按次启动各自的 Docker 容器。已选用常驻端点的工具遇到超时会向调用方返回失败，避免重复执行。检测仍需要匹配宿主机的加速栈与模型，OCR 需要镜像内的模型缓存。具体的设备和数据准备见[检测部署指南](detection-deployment.md)和[分割部署指南](segmentation-deployment.md)。

SAM3 使用独立的 Docker MCP 网关转发到部署者自有的私有推理服务。公开的网关构建只需要网关代码，部署者从 Meta 官方渠道取得权重，推理服务使用 NVIDIA CUDA 和 PyTorch。配置与回退见 [SAM3 网关使用说明](segmentation-deployment.md#docker-mcp-网关)。

已有数据库升级时，按项目迁移顺序应用 [0017_mcp_servers.sql](../backend/sql/migrations/0017_mcp_servers.sql)，再启用外部服务管理。

## 通过管理 API 接入外部 MCP 服务

启用 PostgreSQL 并按既有迁移流程更新数据库。平台使用稳定的 `AUTH_SECRET_KEY` 加密保存外部 Bearer Token。多实例须使用相同密钥。将远端主机加入后端的 `MCP_ALLOWED_HOSTS`，多个主机用逗号分隔。管理 API 接受白名单中的公网 HTTPS 单端点。仅管理员可操作，使用平台已有的管理员登录凭据。

| 管理操作 | 请求 |
| --- | --- |
| 预览可发现的工具、资源和提示模板 | `POST /api/admin/mcp/servers/probe` |
| 注册服务 | `POST /api/admin/mcp/servers` |
| 查看服务及当前状态 | `GET /api/admin/mcp/servers` |
| 启用或停用 | `PATCH /api/admin/mcp/servers/{slug}`，正文为 `{"enabled":true}` 或 `{"enabled":false}` |
| 重新发现工具参数 | `POST /api/admin/mcp/servers/{slug}/refresh` |
| 移除服务 | `DELETE /api/admin/mcp/servers/{slug}` |

探测与注册使用相同的请求格式。将示例域名替换为实际的 MCP 服务。需要认证时可在请求中增加 `auth_bearer_token`。

```json
{
  "slug": "weather",
  "name": "气象数据",
  "transport": "streamable_http",
  "endpoint_url": "https://mcp.example.org/mcp",
  "timeout_seconds": 30,
  "enabled": true
}
```

若服务公开 `forecast`，对话中可见的名称为 `ext_weather__forecast`。服务启停后，本进程立即更新工具列表，其余后端进程定期同步。已经开始执行的调用保有原服务句柄。远端的 `tools/list_changed` 可触发重新发现，缺少通知能力的服务可手动刷新。默认一个回合共可调用外部工具三次。连续三次调用超时会暂停分发一分钟，随后用一次真实调用探测恢复状态。通过 `MCP_HOTPLUG_ENABLED=false` 并重新载入后端配置可关闭外部扩展。

服务器管理员也可设置 `MCP_STATIC_SERVERS_FILE`，指定只允许平台运维维护的 JSON 数组文件。每项采用上面的配置格式。静态标准输入输出服务将 `transport` 设为 `stdio`，用 `stdio_command` 数组传入可执行文件及参数，省略 `endpoint_url`。外部服务收到其工具所声明并通过验证的参数，平台只接受文本证据，影像归属和成果发布由平台处理。

## 知识图谱与编排引擎

内置图谱服务提供目录资源 `ontology://schema/catalog`、当前回合资源 `ontology://session/{session_id}/context` 和 `ontology://session/{session_id}/routes`。订阅当前回合资源后，已验证的成功执行会触发 `notifications/resources/updated`。读取与订阅都需要该回合的账号上下文。栅格、视觉和平台工具共用原有校验、配额、任务登记和结果记录。个人图谱可增加定义，内置前置条件始终参与校验。

默认编排引擎为 AutoGen。要启用 LangGraph，在根目录执行 `uv sync --project backend --extra langgraph`，然后设置 `AGENT_ENGINE_BACKEND=langgraph`。两种引擎共用平台的已启用工具、用户身份、图谱和对话事件格式。需要在运行期间切换时，可在后端启动前设置 `AGENT_ENGINE_BACKEND_FILE` 为受控文件的绝对路径。将内容为 `langgraph` 或 `autogen` 的临时文件在同一目录原子替换为该文件，新回合采用新的值，在途回合沿用原引擎。多实例应共享选择文件或同步替换。普通环境变量变更在重新载入进程配置后生效。

Streamable HTTP 客户端按服务端实际能力协商。新版使用逐请求协议，旧版服务使用初始化握手并可返回 `Mcp-Session-Id`。协议和框架的分工可参阅 [MCP 版本变更](https://modelcontextprotocol.io/specification/2026-07-28/changelog)、[会话式传输规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)与 [FastMCP 文档](https://gofastmcp.com/docs/getting-started/welcome)。
