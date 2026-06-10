from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import app.db.pool as pool_module


class FakePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def reset_pool_state() -> None:
    pool_module._pool = None
    pool_module._pool_initialized = False


def settings(**overrides):
    values = {
        "database_enabled": True,
        "database_url": "postgresql://user:pass@127.0.0.1:15432/app",
        "database_pool_min_size": 1,
        "database_pool_max_size": 5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def isolate_pool(monkeypatch):
    reset_pool_state()
    monkeypatch.setattr(pool_module, "get_settings", lambda: settings())
    yield
    reset_pool_state()


@pytest.mark.asyncio
async def test_get_db_pool_does_not_retry_after_failed_initialization(monkeypatch) -> None:
    calls = 0

    async def create_pool(**_):
        nonlocal calls
        calls += 1
        raise ConnectionRefusedError("database is offline")

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(create_pool=create_pool))

    assert await pool_module.get_db_pool() is None
    assert await pool_module.get_db_pool() is None

    assert calls == 1


@pytest.mark.asyncio
async def test_get_db_pool_returns_existing_pool_without_reinitializing(monkeypatch) -> None:
    created_pool = FakePool()
    calls = 0

    async def create_pool(**_):
        nonlocal calls
        calls += 1
        return created_pool

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(create_pool=create_pool))

    assert await pool_module.get_db_pool() is created_pool
    assert await pool_module.get_db_pool() is created_pool

    assert calls == 1


@pytest.mark.asyncio
async def test_close_db_pool_resets_state_and_allows_reinitialization(monkeypatch) -> None:
    created_pools = [FakePool(), FakePool()]

    async def create_pool(**_):
        return created_pools.pop(0)

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(create_pool=create_pool))

    first_pool = await pool_module.get_db_pool()
    await pool_module.close_db_pool()
    second_pool = await pool_module.get_db_pool()

    assert first_pool is not second_pool
    assert first_pool.closed is True
    assert second_pool.closed is False


@pytest.mark.asyncio
async def test_database_disabled_marks_pool_initialized_without_importing_asyncpg(monkeypatch) -> None:
    monkeypatch.setattr(
        pool_module,
        "get_settings",
        lambda: settings(database_enabled=False),
    )

    assert await pool_module.get_db_pool() is None
    assert pool_module._pool_initialized is True


@pytest.mark.asyncio
async def test_empty_database_url_marks_pool_initialized_without_importing_asyncpg(monkeypatch) -> None:
    monkeypatch.setattr(
        pool_module,
        "get_settings",
        lambda: settings(database_url=""),
    )

    assert await pool_module.get_db_pool() is None
    assert pool_module._pool_initialized is True
