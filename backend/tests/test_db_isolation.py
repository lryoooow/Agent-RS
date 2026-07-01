"""db_isolation 工具的单元测试。

覆盖：正常解析、库名派生、显式覆盖、空/异常分支、共享库护栏判定、
以及最关键的回归断言——默认派生的测试库必须与应用库不同名（修复"重启后账号失效"根因）。
"""
from __future__ import annotations

import pytest

from tests import db_isolation

_APP_DSN = "postgresql://agent_rs:agent_rs_local@127.0.0.1:15432/agent_rs"
_APP_DSN_TEST = "postgresql://agent_rs:agent_rs_local@127.0.0.1:15432/agent_rs_test"


# ---------------------------- db_name ----------------------------


@pytest.mark.parametrize(
    "dsn, expected",
    [
        (_APP_DSN, "agent_rs"),
        (_APP_DSN_TEST, "agent_rs_test"),
        ("postgresql://u:p@localhost:5432/my_db", "my_db"),
        ("postgresql://u:p@localhost:5432/my_db?sslmode=require", "my_db"),
        ("postgresql://u:p@localhost:5432/", ""),
        ("", ""),
    ],
)
def test_db_name(dsn, expected):
    assert db_isolation.db_name(dsn) == expected


# ---------------------------- with_dbname ----------------------------


def test_with_dbname_replaces_only_dbname():
    out = db_isolation.with_dbname(_APP_DSN, "agent_rs_test")
    assert out == _APP_DSN_TEST
    # host/端口/凭据保持不变
    assert db_isolation.db_name(out) == "agent_rs_test"


def test_with_dbname_preserves_query_string():
    dsn = "postgresql://u:p@host:5432/orig?sslmode=require&application_name=x"
    out = db_isolation.with_dbname(dsn, "other")
    assert db_isolation.db_name(out) == "other"
    assert "sslmode=require" in out
    assert "application_name=x" in out


# ---------------------------- is_shared_with_app ----------------------------


def test_shared_same_host_port_and_name():
    assert db_isolation.is_shared_with_app(_APP_DSN, _APP_DSN) is True


def test_not_shared_different_name_same_host():
    assert db_isolation.is_shared_with_app(_APP_DSN_TEST, _APP_DSN) is False


def test_not_shared_different_host_same_name():
    other_host = "postgresql://agent_rs:agent_rs_local@127.0.0.2:15432/agent_rs"
    assert db_isolation.is_shared_with_app(other_host, _APP_DSN) is False


def test_not_shared_different_port_same_name():
    other_port = "postgresql://agent_rs:agent_rs_local@127.0.0.1:5432/agent_rs"
    assert db_isolation.is_shared_with_app(other_port, _APP_DSN) is False


def test_not_shared_when_app_dsn_empty():
    assert db_isolation.is_shared_with_app(_APP_DSN_TEST, "") is False


def test_not_shared_when_test_dsn_empty():
    assert db_isolation.is_shared_with_app("", _APP_DSN) is False


# ---------------------------- resolve_test_dsn ----------------------------


def test_resolve_explicit_env_override_respected(monkeypatch):
    explicit = "postgresql://u:p@db.example.com:5432/custom_ci_db"
    monkeypatch.setenv("TEST_DATABASE_URL", explicit)
    # 显式值原样返回（即便与潜在应用库同名，也由 is_shared_with_app 兜底，不在本层改写）。
    assert db_isolation.resolve_test_dsn() == explicit


def test_resolve_default_derives_test_suffix_from_app(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(db_isolation, "app_dsn_from_env", lambda: _APP_DSN)
    resolved = db_isolation.resolve_test_dsn()
    assert db_isolation.db_name(resolved) == "agent_rs_test"
    # 仅库名变化，连接参数随应用库
    assert "127.0.0.1:15432" in resolved


def test_resolve_fallback_when_no_app_dsn(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(db_isolation, "app_dsn_from_env", lambda: "")
    resolved = db_isolation.resolve_test_dsn()
    # 应用库为空 → 用兜底 DSN 派生 agent_rs_test
    assert db_isolation.db_name(resolved) == "agent_rs_test"


def test_regression_default_test_db_differs_from_app_db(monkeypatch):
    """核心回归：无显式 TEST_DATABASE_URL 时，测试库必须与应用库物理隔离。"""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(db_isolation, "app_dsn_from_env", lambda: _APP_DSN)
    resolved = db_isolation.resolve_test_dsn()
    assert db_isolation.db_name(resolved) != db_isolation.db_name(_APP_DSN)
    assert db_isolation.is_shared_with_app(resolved, _APP_DSN) is False


# ---------------------------- app_dsn_from_env ----------------------------


def test_app_dsn_from_env_returns_settings_url():
    # 正常环境（有 .env）应回非空的应用库 DSN；裸环境（无 .env）database_url 默认为空，亦合法。
    url = db_isolation.app_dsn_from_env()
    assert isinstance(url, str)


class _RaisingGetSettings:
    """同时具备 cache_clear，避免污染 autouse 的 _reset_global_caches。"""

    def __call__(self, *args, **kwargs):
        raise RuntimeError("settings 不可用")

    def cache_clear(self):  # pragma: no cover - 仅为兼容 autouse 夹具
        return None


def test_app_dsn_from_env_returns_empty_on_exception(monkeypatch):
    # settings 抛错时不得向外冒泡，返回空串让上层走兜底。
    import app.core.settings as settings_module

    monkeypatch.setattr(settings_module, "get_settings", _RaisingGetSettings())
    assert db_isolation.app_dsn_from_env() == ""


# ---------------------------- ensure_test_database（集成，需 PG） ----------------------------


async def test_ensure_test_database_creates_and_is_idempotent():
    import asyncpg

    throwaway = "postgresql://agent_rs:agent_rs_local@127.0.0.1:15432/agent_rs_isolation_selftest"
    admin = db_isolation.with_dbname(throwaway, "postgres")
    try:
        conn = await asyncpg.connect(dsn=admin)
    except Exception as exc:
        pytest.skip(f"测试 PostgreSQL 不可达（{exc}）；请先 `docker compose up -d db`")

    async def _exists() -> bool:
        return bool(await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_isolation.db_name(throwaway)
        ))

    try:
        # 预清理：若历史残留则先删，保证从干净态开始
        if await _exists():
            await conn.execute(f'DROP DATABASE "{db_isolation.db_name(throwaway)}"')
        assert await _exists() is False

        # 首次：应创建
        await db_isolation.ensure_test_database(throwaway)
        assert await _exists() is True

        # 再次：幂等，不报错、仍存在
        await db_isolation.ensure_test_database(throwaway)
        assert await _exists() is True
    finally:
        if await _exists():
            await conn.execute(f'DROP DATABASE "{db_isolation.db_name(throwaway)}"')
        await conn.close()


async def test_ensure_test_database_rejects_missing_dbname():
    # DSN 无库名时应在落库前就报错，而不是去 CREATE DATABASE ""。
    with pytest.raises(ValueError):
        await db_isolation.ensure_test_database("postgresql://u:p@127.0.0.1:15432/")
