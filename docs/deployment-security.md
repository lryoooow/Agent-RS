# 独占部署的可选安全模板

共享服务器的现有系统、服务账号、端口和数据库配置不在当前修改范围内。以下仅供未来独占部署评估，不能直接套用到现有共享服务器。

平台管理员在同一登录页输入 `admin` 登录；普通用户继续使用邮箱。管理权限依赖服务端 `AUTH_ADMIN_USER_IDS` 中的活跃用户 ID，账号名称和邮箱不能自行授予权限。管理员密码仅保存加盐哈希，不写入配置或仓库。

- 平台运行使用 `agent-rs` 专用账号，读配置所需的组为 `agent-rs-data`；不要让服务默认以 root 启动。
- 平台解释器和依赖须放在运行账号可访问的位置，不要依赖 `/root` 中的 Python。SAM3 独立 GPU 环境保持独立。
- 上线配置设置 `DEPLOYMENT_ENVIRONMENT=production`，要求登录、PostgreSQL及有效凭据；管理员通过 `AUTH_ADMIN_USER_IDS` 单独配置。
- Compose 数据库和 MinIO 默认仅监听本机。启动前在私有根 `.env` 或环境中设置 `AGENT_RS_DB_PASSWORD`、`AGENT_RS_MINIO_PASSWORD`，并与后端连接配置保持一致；这些值不提交仓库。
- 已有 PostgreSQL 数据卷不会因为修改 Compose 环境变量自动修改数据库角色口令。先协调数据库角色与应用连接配置，再重启验证；不删除数据卷。
- Docker 工具执行需要单独核对权限。加入 docker 组会带来宿主机管理能力，不能把它描述成完整的权限隔离；服务器实际采用的工具入口必须在发布时验证。
- 大型数据库可先在维护安排中 `CREATE INDEX CONCURRENTLY ... ON public.document_chunks(document_id)`，确认成功后应用0015迁移，避免普通建索引的写锁影响。迁移本身不在事务中执行并发建索引。

当前本地修复不代表服务器已经应用以上配置。发布记录须包括真实运行用户、有效监听地址、迁移及服务健康结果。
