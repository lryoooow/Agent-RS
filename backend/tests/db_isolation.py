"""测试库与应用库的物理隔离工具。

背景（见 tests/conftest.py 的 _truncate_between_tests）：PG 仓储测试用例之间靠
`TRUNCATE 所有业务表 CASCADE` 做隔离。若测试库与应用运行库是同一个物理库，每次跑测试都会
清空真实注册账号/会话/历史——这正是"重启后账号失效"的根因。

本模块从根源杜绝该问题：
  - resolve_test_dsn 默认派生一个与应用库隔离的 *_test 库；
  - is_shared_with_app 提供兜底护栏：即便显式把 TEST_DATABASE_URL 指向应用库，也能在
    pg_pool 里识别出来并拒绝运行，绝不让 TRUNCATE 落到真实数据上；
  - ensure_test_database 自动 CREATE 这个独立测试库（首次即建，幂等）。

所有纯函数单独成模块，便于单元测试（见 test_db_isolation.py）。
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

# 无 .env / 无应用 DSN 的裸环境兜底（与 docker-compose 对齐）。仅用于派生测试库。
_FALLBACK_DSN = "postgresql://agent_rs:agent_rs_local@127.0.0.1:15432/agent_rs"
# 派生测试库时给应用库名追加的后缀，保证与应用库不同名。
_TEST_DB_SUFFIX = "_test"


def db_name(dsn: str) -> str:
    """从 postgres DSN 解析数据库名（URL 的 path 段）。空/非法 DSN 返回空串。"""
    if not dsn:
        return ""
    return urlsplit(dsn).path.strip("/")


def with_dbname(dsn: str, new_dbname: str) -> str:
    """返回把 DSN 数据库名替换为 new_dbname 的新 DSN（host/端口/凭据保持不变）。"""
    parts = urlsplit(dsn)
    return urlunsplit(parts._replace(path="/" + new_dbname))


def app_dsn_from_env() -> str:
    """应用运行时所用的 DATABASE_URL（读 settings/.env）。DB 关闭或读不到时返回空串。

    读不到不抛错（返回空串）：调用方据此判断"应用未启用库"，此时无应用数据需保护。
    """
    try:
        from app.core.settings import get_settings

        return get_settings().database_url or ""
    except Exception:
        return ""


def resolve_test_dsn() -> str:
    """解析测试用 DSN，默认与应用库物理隔离。

    优先级：
      1) 显式 TEST_DATABASE_URL 环境变量（尊重用户指定，但仍由 is_shared_with_app 兜底拦截）；
      2) 否则从应用 DSN 派生 <应用库名>_test 库；
      3) 连应用 DSN 都没有（裸环境）时，从 _FALLBACK_DSN 派生 agent_rs_test。
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = app_dsn_from_env() or _FALLBACK_DSN
    name = db_name(base) or "agent_rs"
    return with_dbname(base, name + _TEST_DB_SUFFIX)


def is_shared_with_app(test_dsn: str, app_dsn: str) -> bool:
    """测试库是否与应用库是同一物理库（同 host:port 且同库名）。

    应用未配库（app_dsn 为空）时返回 False——没有应用数据需要保护。
    仅在 host:port 完全一致且库名相同时判为"共享"，避免误伤。
    """
    if not app_dsn or not test_dsn:
        return False
    test_parts, app_parts = urlsplit(test_dsn), urlsplit(app_dsn)
    return (
        test_parts.hostname == app_parts.hostname
        and test_parts.port == app_parts.port
        and db_name(test_dsn) == db_name(app_dsn)
    )


async def ensure_test_database(test_dsn: str) -> None:
    """目标测试库不存在则创建：连维护库 `postgres` 执行 CREATE DATABASE。

    CREATE DATABASE 不能在事务块内运行，故用裸连接（asyncpg 单语句默认 autocommit，
    不包裹在 transaction() 内）。库名含下划线/字母数字，用标识符引号包裹防意外解析。
    """
    import asyncpg

    target = db_name(test_dsn)
    if not target:
        raise ValueError("test_dsn 缺少数据库名，无法建测试库")
    admin_dsn = with_dbname(test_dsn, "postgres")
    conn = await asyncpg.connect(dsn=admin_dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{target}"')
    finally:
        await conn.close()
