# 部署指南（P3 制度化）

## 反向代理要求（生产）
- 前端静态资源与 `/api` **同源**转发（前端基址为相对 `/api`；如分离部署，
  构建时设 `VITE_API_BASE=https://api.example.com` 并配后端 CORS）。
- 透传 `Set-Cookie`（会话 cookie `agent_rs_session`，Path=/api）。
- `/api/chat` 是 SSE：关闭响应缓冲（nginx: `proxy_buffering off;
  proxy_read_timeout 600s`）。前端有 90s 空闲看门狗与断流报错兜底。
- 建议注入 `X-Request-ID`；后端会透传并在响应头回显，日志按它关联。

## 后端监听地址（G23）
- `ops/agent-rs.service` 的 uvicorn 绑定 `--host 127.0.0.1`（2026-10-10 起，
  原为 `0.0.0.0`）。生产流量一律经同机反向代理进入——`--forwarded-allow-ips=
  127.0.0.1` 本就以同机代理为前提，后端没必要再对公网直开 5173。
- **没有反向代理的部署**（如内网直连调试）：把 unit 里的 `--host` 改回
  `0.0.0.0` 前，必须先确认主机防火墙只放行可信网段访问 5173（示例：
  `firewall-cmd --permanent --add-rich-rule='rule family=ipv4 source
  address=<可信网段 CIDR> port port=5173 protocol=tcp accept'`），否则后端
  （含影像下载、报告下载等接口）将直接暴露。
- 生产机同步步骤：仓库改动只落在 `ops/agent-rs.service`，需人工同步到
  生产机 `/etc/systemd/system/agent-rs.service` 后执行
  `sudo systemctl daemon-reload && sudo systemctl restart agent-rs`，
  并验证 `ss -tlnp | grep 5173` 只显示 `127.0.0.1:5173`。

## 错误契约
所有错误响应唯一信封 `{"error":{"code","message"}}`（详见
`backend/app/api/errors.py` 的状态码规则）。`/api/health` 存储不可写时
返回 **503**——探活按状态码报警。

## 观测
每个请求完成输出结构化日志：`http.request id= method= path= status=
duration_ms= user=`；工具调用审计 `tool.invoke`（engine/tools.py）。
出网超时统一在 settings（stac 20s / tavily 15s / ai 60s / geocode 5s）。

## 降级模式
`DATABASE_ENABLED=false`：登录/历史/知识库/记忆 503，聊天与影像分析可用
（默认用户）。`AUTH_SECRET_KEY` 为默认值且 DB 开启时拒绝登录（防误部署）。
