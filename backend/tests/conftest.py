"""全局测试夹具。

1) `_reset_global_caches`（autouse）：每个用例前后重置进程级缓存与 settings，消除跨用例状态污染（M9）。
   根因：`app.agent.search.cache` 的三个单例（decision/result/planner_decision）是进程级的，
   惰性构造时会捕获当时的 settings（TTL/size）。若不重置：
     ① 一个用例缓存的 planner 决策可能命中后一个用例的相同 query+scope，掩盖回归；
     ② 先构造的单例会冻结旧 settings，后续用例 monkeypatch 缓存配置不生效。
   做法：把模块级单例置 None，下次 get_* 会用当前 settings 重建（比对旧实例 clear() 更彻底）。

2) PG 仓储测试夹具（`pg_pool`/`pg_conn`/`_truncate_between_tests`）：连【独立测试库】
   PostgreSQL（docker compose 的 pgvector/pg16），跑迁移建 schema。原置于 tests/db/conftest.py，
   上提到全局是因 tests/ai/ 的报告生成测试（test_report_quality.py）也需复用同一 PG 池。
   - session 级 `pg_pool`：连独立测试库（默认派生 *_test 库，见 db_isolation.resolve_test_dsn），
     建 asyncpg 池，跑一次 `sql.apply.run_migrations` 建好全部表。库不存在则自动 CREATE。
     兜底护栏：若测试库与应用库同名（即便显式 TEST_DATABASE_URL 指过去），整组 skip——
     绝不让 TRUNCATE 清空真实注册账号（修复"重启后账号失效"根因）。库不可达时也整组 skip，
     不让无库环境假绿，也不硬红。
   - function 级 `pg_conn` / 自动 `_truncate_between_tests`：每个用例后 TRUNCATE 所有业务表
     （仅作用于独立测试库，保留 schema_migrations，避免重复跑迁移），保证用例间零状态污染。
     仅对用到 pg_pool 的用例生效。
   仓储函数内部自取 `pool.acquire()`，无法共享单一事务，故用 TRUNCATE 而非事务回滚做隔离——
   对 asyncpg 池最稳、与被测代码零耦合；代价是必须有独立测试库（已在 pg_pool 保证）。
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from tests.db_isolation import (
    app_dsn_from_env,
    db_name,
    ensure_test_database,
    is_shared_with_app,
    resolve_test_dsn,
)


@pytest.fixture(autouse=True)
def _reset_global_caches():
    import app.agent.search.cache as cache_module
    from app.core.settings import get_settings

    def _reset() -> None:
        cache_module._decision_cache = None
        cache_module._result_cache = None
        cache_module._planner_decision_cache = None
        get_settings.cache_clear()

    _reset()
    yield
    _reset()


# 业务表全集（两 schema），按"无依赖顺序 + CASCADE"清空；schema_migrations 不在内，保留迁移记录。
# 注意：与当前迁移集合保持一致——曾经存在但随功能下线而移除的表（如 invites）不可留在这里，
# 否则在全新测试库上 TRUNCATE 会因表不存在而整组用例 ERROR。_truncate_between_tests 另有
# "只清已存在表"的容错兜底，双重保险防止表清单漂移再打挂测试。
_BUSINESS_TABLES = (
    "agent_rs.messages",
    "agent_rs.conversations",
    "agent_rs.sessions",
    "agent_rs.memberships",
    "agent_rs.workspaces",
    "agent_rs.users",
    "public.document_chunks",
    "public.documents",
    "public.document_ingest_jobs",
    "public.embedding_retry",
    "public.memories",
    "public.imagery",
    "public.tool_jobs",
)

_TEST_DSN = resolve_test_dsn()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg_pool():
    """session 级 asyncpg 池 + 迁移，连【独立测试库】。库不可达 → 整组 skip。

    loop_scope=session：池与其连接绑定在 session 级 event loop 上，用例（同 loop_scope）
    复用同一 loop，避免 asyncpg "attached to a different loop"。

    护栏（修复"重启后账号失效"根因）：先确认测试库与应用库不是同一物理库。
    若同名（即便显式 TEST_DATABASE_URL 指向应用库），整组 skip，绝不让
    _truncate_between_tests 清空真实注册账号/会话/历史。
    """
    try:
        import asyncpg
    except ImportError:  # pragma: no cover - asyncpg 是主依赖，正常环境必有
        pytest.skip("asyncpg 未安装")

    app_dsn = app_dsn_from_env()
    if is_shared_with_app(_TEST_DSN, app_dsn):
        pytest.skip(
            f"拒绝测试库与应用库同名（{db_name(_TEST_DSN)}）；已跳过全部 PG 用例以防清空真实数据。"
            " 请勿把 TEST_DATABASE_URL 指向应用库——默认会自动派生独立 *_test 库。"
        )

    try:
        await ensure_test_database(_TEST_DSN)
        pool = await asyncpg.create_pool(dsn=_TEST_DSN, min_size=1, max_size=4)
    except Exception as exc:  # 库未起/连不上/无建库权限
        pytest.skip(f"测试 PostgreSQL 不可达（{exc}）；请先 `docker compose up -d db`")

    from sql.apply import run_migrations

    async with pool.acquire() as conn:
        await run_migrations(conn, log=None)

    yield pool
    await pool.close()


@pytest_asyncio.fixture(loop_scope="session")
async def pg_conn(pg_pool):
    """function 级连接：用例直接在其上跑 SQL/仓储函数。"""
    async with pg_pool.acquire() as conn:
        yield conn


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _truncate_between_tests(request):
    """每个用例后清空业务表（仅对用到 pg_pool 的用例生效），隔离状态。

    容错：只清"当前测试库中实际存在"的业务表。迁移删表/功能下线导致清单里出现不存在的表时，
    自动跳过而非整组用例 ERROR（schema 漂移兜底）。表不存在本就无测试数据可清，跳过零副作用。
    """
    yield
    if "pg_pool" not in request.fixturenames:
        return
    pool = request.getfixturevalue("pg_pool")
    async with pool.acquire() as conn:
        existing = await conn.fetch(
            """
            SELECT quote_ident(table_schema) || '.' || quote_ident(table_name) AS fq
            FROM information_schema.tables
            WHERE (table_schema || '.' || table_name = ANY($1::text[]))
              AND table_type = 'BASE TABLE'
            """,
            list(_BUSINESS_TABLES),
        )
        names = [row["fq"] for row in existing]
        if names:
            await conn.execute(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE")
