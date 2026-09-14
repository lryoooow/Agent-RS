# 部署指南（P3 制度化）

## 反向代理要求（生产）
- 前端静态资源与 `/api` **同源**转发（前端基址为相对 `/api`；如分离部署，
  构建时设 `VITE_API_BASE=https://api.example.com` 并配后端 CORS）。
- 透传 `Set-Cookie`（会话 cookie `agent_rs_session`，Path=/api）。
- `/api/chat` 是 SSE：关闭响应缓冲（nginx: `proxy_buffering off;
  proxy_read_timeout 600s`）。前端有 90s 空闲看门狗与断流报错兜底。
- 建议注入 `X-Request-ID`；后端会透传并在响应头回显，日志按它关联。

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
